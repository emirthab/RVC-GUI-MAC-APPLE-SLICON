import random
import string
from tkinter import filedialog
import soundfile as sf
import tkinter as tk
import customtkinter as ctk
from my_utils import load_audio
import os
import sys
import torch
import warnings
import customtkinter as ctk

now_dir = os.getcwd()
sys.path.append(now_dir)
tmp = os.path.join(now_dir, "TEMP")
os.makedirs(os.path.join(now_dir, "models"), exist_ok=True)
os.makedirs(os.path.join(now_dir, "output"), exist_ok=True)
os.environ["TEMP"] = tmp
warnings.filterwarnings("ignore")
torch.manual_seed(114514)

from vc_infer_pipeline import VC
from fairseq import checkpoint_utils
from scipy.io import wavfile
from infer_pack.models import SynthesizerTrnMs256NSFsid, SynthesizerTrnMs256NSFsid_nono
from multiprocessing import cpu_count
import threading
from time import sleep
from time import sleep
import traceback
import numpy as np
import subprocess
import zipfile

def extract_model_from_zip(zip_path, output_dir):
    # Extract the folder name from the zip file path
    folder_name = os.path.splitext(os.path.basename(zip_path))[0]

    # Create a folder with the same name as the zip file inside the output directory
    output_folder = os.path.join(output_dir, folder_name)
    os.makedirs(output_folder, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for member in zip_ref.namelist():
            if member.endswith('.pth') or member.endswith('.npy') or member.endswith('.index'):
                # Extract the file to the output folder
                zip_ref.extract(member, output_folder)

                # Move the file to the top level of the output folder
                file_path = os.path.join(output_folder, member)
                new_path = os.path.join(output_folder, os.path.basename(file_path))
                os.rename(file_path, new_path)

    print(f"Model files extracted to folder: {output_folder}")
    
    
def play_audio(file_path):
    if sys.platform == 'win32':
        audio_file = os.path.abspath(file_path)
        subprocess.call(['start', '', audio_file], shell=True)
    elif sys.platform == 'darwin':
        audio_file = 'path/to/audio/file.wav'
        subprocess.call(['open', audio_file])
    elif sys.platform == 'linux':
        audio_file = 'path/to/audio/file.wav'
        subprocess.call(['xdg-open', audio_file])

def get_full_path(path):
    return os.path.abspath(path)

hubert_model = None
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
is_half = True if device == "cuda" else False

def load_hubert():
    global hubert_model
    models, _, _ = checkpoint_utils.load_model_ensemble_and_task(
        ["hubert_base.pt"],
        suffix="",
    )
    hubert_model = models[0]
    hubert_model = hubert_model.to(device)
    if is_half:
        hubert_model = hubert_model.half()
    else:
        hubert_model = hubert_model.float()
    hubert_model.eval()


def vc_single(
    sid,
    input_audio,
    f0_up_key,
    f0_file,
    f0_method,
    file_index,
    file_big_npy,
    index_rate,
    output_path=None,
):  # spk_item, input_audio0, vc_transform0,f0_file,f0method0
    global tgt_sr, net_g, vc, hubert_model
    if input_audio is None:
        return "You need to upload an audio", None
    f0_up_key = int(f0_up_key)
    try:
        audio = load_audio(input_audio, 16000)
        times = [0, 0, 0]
        if hubert_model == None:
            load_hubert()
        if_f0 = cpt.get("f0", 1)
        file_index = (
            file_index.strip(" ")
            .strip('"')
            .strip("\n")
            .strip('"')
            .strip(" ")
            .replace("trained", "added")
        )  # 防止小白写错，自动帮他替换掉
        file_big_npy = (
            file_big_npy.strip(" ").strip('"').strip(
                "\n").strip('"').strip(" ")
        )
        audio_opt = vc.pipeline(
            hubert_model,
            net_g,
            sid,
            audio,
            times,
            f0_up_key,
            f0_method,
            file_index,
            file_big_npy,
            index_rate,
            if_f0,
            f0_file=f0_file,
        )
        print(
            "npy: ", times[0], "s, f0: ", times[1], "s, infer: ", times[2], "s", sep=""
        )

        if output_path is not None:
            sf.write(output_path, audio_opt, tgt_sr)

        return "Success", (tgt_sr, audio_opt)
    except:
        info = traceback.format_exc()
        print(info)
        return info, (None, None)


def vc_multi(
    sid,
    dir_path,
    opt_root,
    paths,
    f0_up_key,
    f0_method,
    file_index,
    file_big_npy,
    index_rate,
):
    try:
        dir_path = (
            dir_path.strip(" ").strip('"').strip("\n").strip('"').strip(" ")
        )  # 防止小白拷路径头尾带了空格和"和回车
        opt_root = opt_root.strip(" ").strip(
            '"').strip("\n").strip('"').strip(" ")
        os.makedirs(opt_root, exist_ok=True)
        try:
            if dir_path != "":
                paths = [os.path.join(dir_path, name)
                         for name in os.listdir(dir_path)]
            else:
                paths = [path.name for path in paths]
        except:
            traceback.print_exc()
            paths = [path.name for path in paths]
        infos = []
        for path in paths:
            info, opt = vc_single(
                sid,
                path,
                f0_up_key,
                None,
                f0_method,
                file_index,
                file_big_npy,
                index_rate,
            )
            if info == "Success":
                try:
                    tgt_sr, audio_opt = opt
                    wavfile.write(
                        "%s/%s" % (opt_root, os.path.basename(path)
                                   ), tgt_sr, audio_opt
                    )
                except:
                    info = traceback.format_exc()
            infos.append("%s->%s" % (os.path.basename(path), info))
            yield "\n".join(infos)
        yield "\n".join(infos)
    except:
        yield traceback.format_exc()


def get_vc(weight_path, sid):

    global n_spk, tgt_sr, net_g, vc, cpt
    if sid == []:
        global hubert_model
        if hubert_model != None:  # 考虑到轮询, 需要加个判断看是否 sid 是由有模型切换到无模型的
            print("clean_empty_cache")
            del net_g, n_spk, vc, hubert_model, tgt_sr  # ,cpt
            hubert_model = net_g = n_spk = vc = hubert_model = tgt_sr = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            # 楼下不这么折腾清理不干净
            if_f0 = cpt.get("f0", 1)
            if if_f0 == 1:
                net_g = SynthesizerTrnMs256NSFsid(
                    *cpt["config"], is_half=is_half)
            else:
                net_g = SynthesizerTrnMs256NSFsid_nono(*cpt["config"])
            del net_g, cpt
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            cpt = None
        return {"visible": False, "__type__": "update"}
    person = weight_path
    print("loading %s" % person)
    cpt = torch.load(person, map_location="cpu")
    tgt_sr = cpt["config"][-1]
    cpt["config"][-3] = cpt["weight"]["emb_g.weight"].shape[0]  # n_spk
    if_f0 = cpt.get("f0", 1)
    if if_f0 == 1:
        net_g = SynthesizerTrnMs256NSFsid(*cpt["config"], is_half=is_half)
    else:
        net_g = SynthesizerTrnMs256NSFsid_nono(*cpt["config"])
    del net_g.enc_q
    print(net_g.load_state_dict(cpt["weight"], strict=False))  # 不加这一行清不干净, 真奇葩
    net_g.eval().to(device)
    if is_half:
        net_g = net_g.half()
    else:
        net_g = net_g.float()
    vc = VC(tgt_sr, device, is_half)
    n_spk = cpt["config"][-3]
    return {"visible": True, "maximum": n_spk, "__type__": "update"}


def clean():
    return {"value": "", "__type__": "update"}


def if_done(done, p):
    while 1:
        if p.poll() == None:
            sleep(0.5)
        else:
            break
    done[0] = True


def if_done_multi(done, ps):
    while 1:
        # poll==None代表进程未结束
        # 只要有一个进程未结束都不停
        flag = 1
        for p in ps:
            if p.poll() == None:
                flag = 0
                sleep(0.5)
                break
        if flag == 1:
            break
    done[0] = True


# window


def outputkey(length=5):
    # generate all possible characters
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))
# choose `length` characters randomly from the list and join them into a string

def refresh_model_list():
    global model_folders
    model_folders = [f for f in os.listdir(models_dir) if os.path.isdir(os.path.join(
    models_dir, f)) and any(f.endswith(".pth") for f in os.listdir(os.path.join(models_dir, f)))]
    model_list.configure(values=model_folders)
    model_list.update()

def browse_zip():
    global zip_file
    zip_file = filedialog.askopenfilename(
        initialdir=os.getcwd(),
        title="Select file",
        filetypes=(("zip files", "*.zip"), ("all files", "*.*")),
    )
    extract_model_from_zip(zip_file, models_dir)
    refresh_model_list()
    
def get_output_path(file_path):
    print(file_path)
    if not os.path.exists(file_path):
        return file_path  # File path does not exist, return as is

    # Split file path into directory, base filename, and extension
    dir_name, file_name = os.path.split(file_path)
    file_name, file_ext = os.path.splitext(file_name)

    # Initialize index to 1
    index = 1

    # Increment index until a new file path is found
    while True:
        new_file_name = f"{file_name}_RVC_{index}{file_ext}"
        new_file_path = os.path.join(dir_name, new_file_name)
        if not os.path.exists(new_file_path):
            return new_file_path  # Found new file path, return it
        index += 1
    
def on_button_click():
    output_audio_frame.pack_forget()
    result_state.pack_forget()
    run_button.configure(state="disabled")

    # Get values from user input widgets
    sid = sid_entry.get()
    input_audio = input_audio_entry.get()
    f0_pitch = f0_pitch_entry.get()
    f0_file = f0_file_entry.get()
    f0_method = f0_method_entry.get()
    file_index = file_index_entry.get()
    file_big_npy = file_big_npy_entry.get()
    index_rate = round(index_rate_entry.get(),2)
    global output_file
    output_file = get_output_path(input_audio)
    print("sid: ", sid, "input_audio: ", input_audio, "f0_pitch: ", f0_pitch, "f0_file: ", f0_file, "f0_method: ", f0_method,
          "file_index: ", file_index, "file_big_npy: ", file_big_npy, "index_rate: ", index_rate, "output_file: ", output_file)
    # Call the vc_single function with the user input values
    if model_loaded == True and os.path.isfile(input_audio):
        try:
            loading_progress.pack(padx=10, pady=10)
            loading_progress.start()
            
            result, audio_opt = vc_single(
                0, input_audio, f0_pitch, None, f0_method, file_index, file_big_npy, index_rate, output_file)
            # output_label.configure(text=result + "\n saved at" + output_file)
            print(os.path.join(output_file))
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
              print(output_file) 
              
              run_button.configure(state="enabled")
              message = result
              result_state.configure(text_color="green")
              last_output_file.configure(text=output_file)
              output_audio_frame.pack(padx=10, pady=10)
            else: 
              message = result
              result_state.configure(text_color="red")

        except Exception as e:
            print(e)
            message = "Voice conversion failed", e

    # Update the output label with the result
       # output_label.configure(text=result + "\n saved at" + output_file)

        run_button.configure(state="enabled")
    else:
        message = "Please select a model and input audio file"
        run_button.configure(state="enabled")
        result_state.configure(text_color="red")

    loading_progress.stop()
    loading_progress.pack_forget()
    result_state.pack(padx=10, pady=10, side="top")
    result_state.configure(text=message)


def browse_file():
    filepath = filedialog.askopenfilename(
        filetypes=[("Audio Files", "*.wav;*.mp3")])
    filepath = os.path.normpath(filepath)  # Normalize file path
    input_audio_entry.delete(0, tk.END)
    input_audio_entry.insert(0, filepath)


def start_processing():

    t = threading.Thread(target=on_button_click)
    t.start()


# Create tkinter window and widgets
root = ctk.CTk()

root.title("RVC GUI")
root.geometry("800x800")
root.resizable(False, False)

model_loaded = False


def selected_model(choice):

    file_index_entry.delete(0, ctk.END)
    file_big_npy_entry.delete(0, ctk.END)
    model_dir = os.path.normpath(os.path.join(models_dir, choice))
    pth_file = [f for f in os.listdir(model_dir) if os.path.isfile(
        os.path.join(model_dir, f)) and f.endswith(".pth")]
    if pth_file:
        global pth_file_path
        pth_file_path = os.path.join(model_dir, pth_file[0])
        npy_files = [f for f in os.listdir(model_dir) if os.path.isfile(
            os.path.join(model_dir, f)) and (f.endswith(".npy") or f.endswith(".index"))]
        if npy_files:
            npy_files_dir = [os.path.join(model_dir, f) for f in npy_files]
            if len(npy_files_dir) == 2:
                index_file = [
                    f for f in npy_files_dir if f.endswith(".index")][0]
                npy_file = [f for f in npy_files_dir if f.endswith(".npy")][0]
                print(f".pth file directory: {pth_file_path}")
                print(f".index file directory: {index_file}")
                print(f".npy file directory: {npy_file}")

                file_index_entry.insert(0, index_file)
                file_big_npy_entry.insert(0, npy_file)

            else:
                print(
                    f"Incomplete set of .npy and .index files found in {model_dir}")
        else:
            print(f"No .npy or .index files found in {model_dir}")

        get_vc(pth_file_path, 0)
        global model_loaded
        model_loaded = True
    else:
        print(f"No .pth files found in {model_dir}")


def index_slider_event(value):
    index_rate_label.configure(
        text='Feature retrieval rate: %s' % round(value, 2))
   # print(value)


def pitch_slider_event(value):
    f0_pitch_label.configure(text='Pitch: %s' % round(value))
  #  print(value)


def update_config(selected):
    global device, is_half  # declare newconfig as a global variable
    if selected == "GPU":
        device = "cuda:0"
        is_half = True
    else:
        device = "cpu"
        is_half = False

    if "pth_file_path" in globals():
        load_hubert()
        get_vc(pth_file_path, 0)


models_dir = "./models"
model_folders = [f for f in os.listdir(models_dir) if os.path.isdir(os.path.join(
    models_dir, f)) and any(f.endswith(".pth") for f in os.listdir(os.path.join(models_dir, f)))]


master_frame = ctk.CTkFrame(master=root, height=500)
master_frame.pack(padx=5, pady=5)


left_frame = ctk.CTkFrame(master=master_frame, )
left_frame.grid(row=0, column=0, padx=10,  pady=10, sticky="nsew")

right_frame = ctk.CTkFrame(master=master_frame, )
right_frame.grid(row=0, column=1, pady=10, padx=10, sticky="nsew")


inputpath_frame = ctk.CTkFrame(master=left_frame)
inputpath_frame.grid(row=0, column=0, padx=15, pady=10, sticky="nsew")


output_audio_frame = ctk.CTkFrame(master=root)

select_model_frame = ctk.CTkFrame(left_frame)
select_model_frame.grid(row=1, column=0, padx=15, pady=10, sticky="nsew")

pitch_frame = ctk.CTkFrame(left_frame)
pitch_frame.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")



# Get the list of .pth files in the models directory



sid_label = ctk.CTkLabel(select_model_frame, text="Speaker ID:")
sid_entry = ctk.CTkEntry(select_model_frame)
sid_entry.insert(0, "0")
sid_entry.configure(state="disabled")

# intiilizing model select widget
select_model = ctk.StringVar(value="Select a model")
model_list = ctk.CTkOptionMenu(select_model_frame, values=model_folders,
                               command=selected_model,
                               variable=select_model
                               )

# intiilizing audio file input widget
input_audio_label = ctk.CTkLabel(inputpath_frame, text="Input audio file:")
browse_button = ctk.CTkButton(
    inputpath_frame, text="Browse", command=browse_file)
input_audio_entry = ctk.CTkEntry(inputpath_frame)

#  intiilizing pitch widget
f0_pitch_label = ctk.CTkLabel(pitch_frame, text="Pitch: 0")
f0_pitch_entry = ctk.CTkSlider(
    pitch_frame, from_=-20, to=20, number_of_steps=100, command=pitch_slider_event, )
f0_pitch_entry.set(0)

# intiilizing f0 file widget
f0_file_label = ctk.CTkLabel(right_frame, text="F0 file (Optional/Not Tested)")
f0_file_entry = ctk.CTkEntry(right_frame, width=250)

# intiilizing f0 method widget
f0_method_label = ctk.CTkLabel(
    pitch_frame, text="F0 method")
f0_method_entry = ctk.CTkSegmentedButton(
    pitch_frame, height=40, values=["harvest", "pm"])
f0_method_entry.set("harvest")

# intiilizing index file widget
file_index_label = ctk.CTkLabel(right_frame, text=".index File (Recommended)")
file_index_entry = ctk.CTkEntry(right_frame, width=250)

# intiilizing big npy file widget
file_big_npy_label = ctk.CTkLabel(right_frame, text=".npy File (Recommended)")
file_big_npy_entry = ctk.CTkEntry(right_frame, width=250)

# intiilizing index rate widget
index_rate_entry = ctk.CTkSlider(
    right_frame, from_=0, to=1, number_of_steps=20, command=index_slider_event, )
index_rate_entry.set(0.4)
index_rate_label = ctk.CTkLabel(
    right_frame, text="Feature retrieval rate: 0.4" )

# intiilizing run button widget
run_button = ctk.CTkButton(
    left_frame, fg_color="green", hover_color="darkgreen", text="Convert voice", command=start_processing)

# intiilizing output label widget
output_label = ctk.CTkLabel(right_frame, text="")

# intiilizing loading progress bar widget
loading_progress = ctk.CTkProgressBar(master=root, width=200)
loading_progress.configure(mode="indeterminate")

# intiilizing result state label widget
result_state = ctk.CTkLabel(
    root, text="", fg_color="#1C1C1C", height=50, width=100, corner_radius=10)

# intiilizing change device widget
change_device_label = ctk.CTkLabel( right_frame, text="Processing device")
change_device = ctk.CTkSegmentedButton(
    right_frame, command=lambda value: update_config(value))
change_device.configure(
    values=["GPU", "CPU"])

if "cpu" in device.type.lower() or device.type.lower() == "cpu":
    change_device.set("CPU")
    change_device.configure(state="disabled")
   
else:
    change_device.set("GPU")

# intiilizing last output label & open output button widget
last_output_label = ctk.CTkLabel(output_audio_frame, text="Output path: ")
last_output_file = ctk.CTkLabel(output_audio_frame, text="", text_color="green")
open_output_button = ctk.CTkButton(output_audio_frame, text="Open", command=lambda: play_audio(output_file))

# intiilizing import models button widget
import_moodels_button = ctk.CTkButton(right_frame, fg_color="darkred", hover_color="black", corner_radius=20, text="Import model from .zip", command=browse_zip)



# button = ctk.CTkButton(root, text="Open Window", command=open_window)
# button.pack()



# Packing widgets into window
change_device_label.grid(row=1, column=0, columnspan=2, padx=10, pady=5)
change_device.grid(row=2, column=0, columnspan=2, padx=10, pady=5)
last_output_label.grid( pady=10, row=0, column=0)
last_output_file.grid( pady=10, row=0, column=1)
open_output_button.grid(pady=10, row=1, column=0, columnspan=2)
import_moodels_button.grid(padx=10, pady=10, row=0, column=0)
model_list.grid(padx=10, pady=10, row=0, column=2)
sid_label.grid(padx=10, pady=10, row=0, column=0)
sid_entry.grid(padx=0, pady=10, row=0, column= 1)
browse_button.grid(padx=10, pady=10, row=0, column=2)
input_audio_label.grid(padx=10, pady=10, row=0, column=0)
input_audio_entry.grid(padx=10, pady=10, row=0, column=1)
f0_method_label.grid(padx=10, pady=10, row=0, column=0)
f0_method_entry.grid(padx=10, pady=10, row=0, column=1)
f0_pitch_label.grid(padx=10, pady=10, row=1, column=0)
f0_pitch_entry.grid(padx=10, pady=10, row=1, column=1)
f0_file_label.grid(padx=10, pady=10)
f0_file_entry.grid(padx=10, pady=10)
file_index_label.grid(padx=10, pady=10)
file_index_entry.grid(padx=10, pady=10)
file_big_npy_label.grid(padx=10, pady=10)
file_big_npy_entry.grid(padx=10, pady=10)
index_rate_label.grid(padx=10, pady=10)
index_rate_entry.grid(padx=10, pady=10)
run_button.grid(padx=30, pady=30)
output_label.grid(padx=0, pady=10)

root.mainloop()