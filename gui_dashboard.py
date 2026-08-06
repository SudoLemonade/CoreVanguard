import ctypes
import sys
import os

# ==========================================
# 1. BUNDLED ASSET PATH LOGIC
# ==========================================
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS # PyInstaller's temporary memory folder
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

if getattr(sys, 'frozen', False):
    RUN_DIR = os.path.dirname(sys.executable)
else:
    RUN_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(RUN_DIR)

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

if not is_admin():
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{sys.argv[0]}"', None, 1)
    sys.exit()

import customtkinter as ctk
import tkinter as tk
from PIL import Image, ImageTk
import threading
import time
import requests
import psutil
import winreg
import json
import subprocess
import keyboard

# DPI FIX
try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
except: pass

from hardware_monitor import CPUSensor, GPUSensor
from ram_cleaner import clear_standby_memory

# ==========================================
# CLASS: PresentMonReader (OOP Concept: Encapsulation)
# Purpose: Manages the Intel PresentMon background subprocess.
# It encapsulates the complex ETW (Event Tracing for Windows) data stream,
# parsing the raw stdout internally so the main application only has to
# interact with clean, safe data via the get_data() method.
# ==========================================
class PresentMonReader:
    def __init__(self):
        self.current_fps = "--"
        self.active_app = "WAITING FOR GAME..."
        self.process = None
        self.last_frame_time = time.time()
        
        os.system("taskkill /f /im PresentMon.exe >nul 2>&1")
        os.system("logman stop CoreVanguard -ets >nul 2>&1")
        os.system("logman stop PresentMon -ets >nul 2>&1")
        
        self.thread = threading.Thread(target=self._run_presentmon, daemon=True)
        self.thread.start()

    # ---------------------------------------------------------
    # METHOD: _run_presentmon
    # This runs on a dedicated Daemon Thread. It launches the .exe
    # invisibly and reads the pipeline line-by-line to calculate Frame Time.
    # ---------------------------------------------------------

    def _run_presentmon(self):
        try:
            time.sleep(1.0) 
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            pm_path = os.path.join(os.getcwd(), "PresentMon.exe")
            
            self.process = subprocess.Popen(
                [pm_path, "--output_stdout", "--stop_existing_session", "-session_name", "CoreVanguard"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, bufsize=1, startupinfo=startupinfo
            )
            
            while True:
                line = self.process.stdout.readline()
                if not line: break
                clean_line = line.strip()
                if not clean_line or "warning" in clean_line.lower() or "error" in clean_line.lower() or "Application" in clean_line: continue
                    
                parts = clean_line.split(',')
                if len(parts) >= 11:
                    app = parts[0].replace('\xef\xbb\xbf', '').replace('.exe', '')
                    if app.lower() not in ["dwm", "explorer", "systemsettings", "searchapp", "startmenuexperiencehost", "corevanguard", "textinputhost", "cmd", "conhost"]:
                        self.active_app = app.upper()
                        self.last_frame_time = time.time()  
                        ms_val = parts[10].strip()
                        if ms_val != "NA":
                            try:
                                ms = float(ms_val)
                                if ms > 0: self.current_fps = str(int(1000.0 / ms))
                            except: pass
        except Exception:
            self.current_fps = "ERR"
            self.active_app = "CRASH"

    def get_data(self):
        if self.active_app == "CRASH": return "CRASH", "ERR"
        if time.time() - self.last_frame_time > 4.0: return "WAITING FOR GAME...", "--"
        return self.active_app, self.current_fps

    def stop(self):
        if self.process: self.process.kill()
        os.system("taskkill /f /im PresentMon.exe >nul 2>&1")
        os.system("logman stop CoreVanguard -ets >nul 2>&1")

# ==========================================
# CLASS: HUDOverlay (OOP Concept: Inheritance)
# Inherits from: tkinter.Toplevel
# Purpose: Creates a borderless, transparent floating window. By inheriting
# from Toplevel, this class gains all OS-level window management abilities
# while allowing custom rendering for the in-game OSD.
# ==========================================
class HUDOverlay(tk.Toplevel):
    def __init__(self, master_url, parent_app):
        super().__init__()
        self.parent = parent_app
        self.title("CoreVanguard HUD")
        self.geometry("+0+0") 
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#050505")
        self.attributes("-alpha", self.parent.opacity_slider.get())

        self.main_frame = tk.Frame(self, bg="#050505", padx=8, pady=8)
        self.main_frame.pack(fill="both", expand=True)

        self.cpu_name, self.gpu_name = "PROCESSOR", "GRAPHICS"
        try:
            data = requests.get(master_url).json()
            for hw in data.get('Children', [0])[0].get('Children', []):
                text = hw.get('Text', '')
                img = hw.get('ImageURL', '').lower()
                if 'cpu' in img: self.cpu_name = text
                elif any(x in img for x in ['gpu', 'nvidia', 'ati']) or ('intel' in img and 'cpu' not in img): self.gpu_name = text
        except: pass

        tc = self.parent.current_theme
        self.cpu_lbl = tk.Label(self.main_frame, font=("Roboto Mono", 12, "bold"), fg=tc, bg="#050505")
        self.gpu_lbl = tk.Label(self.main_frame, font=("Roboto Mono", 12, "bold"), fg=tc, bg="#050505")
        self.ram_lbl = tk.Label(self.main_frame, font=("Roboto Mono", 12, "bold"), fg=tc, bg="#050505")
        self.fps_lbl = tk.Label(self.main_frame, font=("Roboto Mono", 12, "bold"), fg=tc, bg="#050505")

        self.cpu = CPUSensor("Processor", master_url)
        self.gpu = GPUSensor("Graphics Card", master_url)
        
        self.bind("<ButtonPress-1>", self.start_move)
        self.bind("<B1-Motion>", self.do_move)
        
        self.flash_toggle = False
        self.update_hud()

    def start_move(self, event): self.x, self.y = event.x, event.y
    def do_move(self, event):
        deltax, deltay = event.x - self.x, event.y - self.y
        x, y = self.winfo_x() + deltax, self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")

    def update_hud(self):
        self.attributes("-alpha", self.parent.opacity_slider.get())
        tc = self.parent.current_theme
        self.flash_toggle = not self.flash_toggle
        
        alerts_on = self.parent.config.get("alerts", True)
        anim_on = self.parent.config.get("animations", True)

        if self.parent.cpu_switch.get() == 1:
            try:
                c_t, c_l = self.cpu.fetch_data()
                t_val = float(c_t)
                hw_flag = getattr(self.parent, 'cpu_throttle_hw', False)
                
                color = tc
                warn = ""
                if alerts_on:
                    if hw_flag or t_val >= 88.0:
                        color = ("#FF0000" if self.flash_toggle else "#FFFF00") if anim_on else "#FF0000"
                        warn = " [THROTTLING]" if hw_flag else " [HOT]"
                    elif t_val >= 80.0:
                        color = "#FFA500"
                
                self.cpu_lbl.configure(text=f"{self.cpu_name} (CPU): {int(c_l):02d}% | {c_t}°C{warn}", fg=color)
                if not self.cpu_lbl.winfo_ismapped(): self.cpu_lbl.pack(anchor="w", pady=1)
            except: pass
        else:
            if self.cpu_lbl.winfo_ismapped(): self.cpu_lbl.pack_forget()

        if self.parent.gpu_switch.get() == 1:
            try:
                g_t, g_l = self.gpu.fetch_data()
                t_val = float(g_t)
                hw_flag = getattr(self.parent, 'gpu_throttle_hw', False)
                
                color = tc
                warn = ""
                if alerts_on:
                    if hw_flag or t_val >= 88.0:
                        color = ("#FF0000" if self.flash_toggle else "#FFFF00") if anim_on else "#FF0000"
                        warn = " [THROTTLING]" if hw_flag else " [HOT]"
                    elif t_val >= 80.0:
                        color = "#FFA500"
                
                self.gpu_lbl.configure(text=f"{self.gpu_name} (GPU): {int(g_l):02d}% | {g_t}°C{warn}", fg=color)
                if not self.gpu_lbl.winfo_ismapped(): self.gpu_lbl.pack(anchor="w", pady=1)
            except: pass
        else:
            if self.gpu_lbl.winfo_ismapped(): self.gpu_lbl.pack_forget()

        if self.parent.ram_switch.get() == 1:
            try:
                ram = psutil.virtual_memory()
                self.ram_lbl.configure(text=f"SYS MEMORY (RAM): {int(ram.used/(1024*1024))} MB | {ram.percent}%", fg=tc)
                if not self.ram_lbl.winfo_ismapped(): self.ram_lbl.pack(anchor="w", pady=1)
            except: pass
        else:
            if self.ram_lbl.winfo_ismapped(): self.ram_lbl.pack_forget()

        if self.parent.fps_switch.get() == 1:
            app, fps = self.parent.present_mon.get_data()
            self.fps_lbl.configure(text=f"{app} (FPS): {fps}", fg=tc)
            if not self.fps_lbl.winfo_ismapped(): self.fps_lbl.pack(anchor="w", pady=1)
        else:
            if self.fps_lbl.winfo_ismapped(): self.fps_lbl.pack_forget()

        self.after(300, self.update_hud)

# ==========================================
# CLASS: VectorGauge (OOP Concept: Instantiation & State Management)
# Purpose: A reusable blueprint for rendering circular hardware dials.
# Instead of writing canvas code twice, this class is instantiated as multiple
# independent objects. Each object maintains its own internal variables 
# (like self.is_critical) so animations run independently.
# ==========================================
class VectorGauge:
    def __init__(self, canvas, rel_x, rel_y, title, dial_path):
        self.canvas = canvas
        self.rel_x = rel_x
        self.rel_y = rel_y
        self.img_raw = Image.open(dial_path)
        self.dial_photo = None
        self.img_id = self.canvas.create_image(0, 0)
        self.title_id = self.canvas.create_text(0, 0, text=title, fill="white", font=("Roboto Mono", 12, "bold"))
        self.val_text = self.canvas.create_text(0, 0, text="0%", fill="white", font=("Roboto Mono", 48, "bold"))
        self.temp_text = self.canvas.create_text(0, 0, text="0.0°C", fill="#AAAAAA", font=("Arial", 18, "bold"))
        self.arc_id = self.canvas.create_arc(0, 0, 0, 0, start=225, extent=0, style=tk.ARC, width=14)
        
        self.is_critical = False
        self.flash_state = False
        self.current_color = "#AAAAAA"
        self.anim_enabled = True
        self.last_temp = 0.0  # MEMORY STATE FOR INSTANT THEME REFRESH
        self._animate()

    # ---------------------------------------------------------
    # METHOD: _animate
    # A recursive UI loop using tkinter's .after() method. It checks the 
    # object's internal state every 300ms and pulses colors if a thermal limit is breached.
    # ---------------------------------------------------------

    def _animate(self):
        if self.is_critical:
            if self.anim_enabled:
                self.flash_state = not self.flash_state
                pulse_color = "#FF0000" if self.flash_state else "#440000"
                self.canvas.itemconfig(self.arc_id, outline=pulse_color)
                self.canvas.itemconfig(self.temp_text, fill=pulse_color)
            else:
                self.canvas.itemconfig(self.arc_id, outline="#FF0000")
                self.canvas.itemconfig(self.temp_text, fill="#FF0000")
        self.canvas.after(300, self._animate)

    def reposition(self, win_w, win_h, color):
        self.current_color = color
        x, y = win_w * self.rel_x, win_h * 0.45
        size = int(win_h * 0.35)
        res_img = self.img_raw.resize((size, size), Image.LANCZOS)
        self.dial_photo = ImageTk.PhotoImage(res_img)
        self.canvas.coords(self.img_id, x, y)
        self.canvas.itemconfig(self.img_id, image=self.dial_photo)
        self.canvas.coords(self.title_id, x, y - (size * 0.52))
        self.canvas.coords(self.val_text, x, y - (size * 0.05))
        self.canvas.coords(self.temp_text, x, y + (size * 0.22))
        pad = size * 0.38
        self.canvas.coords(self.arc_id, x-pad, y-pad, x+pad, y+pad)
        
        # INSTANTLY FORCE THE NEW COLOR ON THEME SWAP
        if not self.is_critical:
            self.canvas.itemconfig(self.arc_id, outline=color)
            if self.last_temp < 80.0:
                self.canvas.itemconfig(self.temp_text, fill=color)

    def update_data(self, load, temp, hw_throttle_flag=False, alerts_on=True, anim_on=True):
        self.anim_enabled = anim_on
        self.canvas.itemconfig(self.val_text, text=f"{int(load)}%")
        self.canvas.itemconfig(self.temp_text, text=f"{temp}°C")
        self.canvas.itemconfig(self.arc_id, extent=-(load / 100.0) * 270)
        
        try:
            t_val = float(temp)
            self.last_temp = t_val # Update memory state
            
            if alerts_on:
                if hw_throttle_flag or t_val >= 88.0:
                    self.is_critical = True 
                else:
                    self.is_critical = False
                    if t_val >= 80.0:
                        self.canvas.itemconfig(self.temp_text, fill="#FFA500") 
                        self.canvas.itemconfig(self.arc_id, outline="#FFA500")
                    else:
                        self.canvas.itemconfig(self.temp_text, fill=self.current_color)
                        self.canvas.itemconfig(self.arc_id, outline=self.current_color)
            else:
                self.is_critical = False
                self.canvas.itemconfig(self.temp_text, fill=self.current_color)
                self.canvas.itemconfig(self.arc_id, outline=self.current_color)
        except: pass

# ==========================================
# CLASS: CoreVanguardEngine (OOP Concepts: Inheritance & Composition)
# Inherits from: customtkinter.CTk
# Purpose: The master controller for the entire application. 
# It demonstrates "Composition" (a Has-A relationship) by owning instances 
# of PresentMonReader, CPUSensor, GPUSensor, and multiple VectorGauges.
# ==========================================
class CoreVanguardEngine(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("COREVANGUARD")
        self.geometry("1200x800")
        
        try:
            self.iconbitmap(resource_path("icon.ico"))
            self.after(200, lambda: self.wm_iconbitmap(resource_path("icon.ico")))
        except: pass
        
        self.present_mon = PresentMonReader()
        
        # COLOR LOGIC ENGINE
        self.themes = ["#FF0000", "#00FFFF", "#00FF00", "#FF00FF", "#FFFF00", "#FFFFFF"]
        self.text_colors = ["#FFFFFF", "#000000", "#000000", "#FFFFFF", "#000000", "#000000"]
        self.current_theme_idx = 0
        
        self.config_file = "cv_config.json"
        self.config = {"min_close": True, "start_min": False, "boot": False, "opacity": 0.85, "theme_idx": 0, "hotkey": "shift+h", "alerts": True, "animations": True}
        self.load_config()
        self.current_theme_idx = self.config["theme_idx"]
        self.current_theme = self.themes[self.current_theme_idx]
        self.current_text_color = self.text_colors[self.current_theme_idx]

        self.master_canvas = tk.Canvas(self, bg="black", highlightthickness=0)
        self.master_canvas.pack(fill="both", expand=True)

        self.bg_raw = Image.open(resource_path("app_bg.png"))
        self.bg_id = self.master_canvas.create_image(0, 0, anchor="nw")
        self.logo_raw = Image.open(resource_path("logo.png"))
        self.logo_id = self.master_canvas.create_image(0, 0, anchor="nw")

        self.cpu_gauge = VectorGauge(self.master_canvas, 0.32, 0.45, "CPU ENGINE LOAD", resource_path("dial_base.png"))
        self.gpu_gauge = VectorGauge(self.master_canvas, 0.68, 0.45, "GPU TURBINE LOAD", resource_path("dial_base.png"))
        
        self.hud_instance = None 
        self.cpu_throttle_hw = False
        self.gpu_throttle_hw = False
        
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self._resize_timer = None
        self.bind("<Configure>", self._handle_resize_event)
        
        self.url = "http://localhost:8085/data.json"
        self.cpu = CPUSensor("Processor", self.url)
        self.gpu = GPUSensor("Graphics Card", self.url)
        threading.Thread(target=self.poll_data, daemon=True).start()

        self.apply_hotkey()
        if self.config["start_min"]: self.after(100, self.iconify)

    def load_config(self):
        try:
            with open(self.config_file, "r") as f: self.config.update(json.load(f))
        except: pass

    def save_config(self):
        try:
            with open(self.config_file, "w") as f: json.dump(self.config, f)
        except: pass

    def _handle_resize_event(self, event):
        self.master_canvas.itemconfig(self.bg_id, state='hidden')
        if self._resize_timer is not None: self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(100, self._finalize_resize)

    def _finalize_resize(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 300: return
        res_bg = self.bg_raw.resize((w, h), Image.LANCZOS)
        self.bg_photo = ImageTk.PhotoImage(res_bg)
        self.master_canvas.itemconfig(self.bg_id, image=self.bg_photo, state='normal')
        l_size = int(h * 0.20)
        res_logo = self.logo_raw.resize((l_size, l_size), Image.LANCZOS)
        self.logo_photo = ImageTk.PhotoImage(res_logo)
        self.master_canvas.coords(self.logo_id, 40, 40)
        self.master_canvas.itemconfig(self.logo_id, image=self.logo_photo)
        self.cpu_gauge.reposition(w, h, self.current_theme)
        self.gpu_gauge.reposition(w, h, self.current_theme)

    def _build_ui(self):
        self.panel = ctk.CTkFrame(self, fg_color="#080808", corner_radius=15, border_width=2, border_color=self.current_theme)
        self.panel.place(relx=0.5, rely=0.85, anchor="center", relwidth=0.96, relheight=0.25)
        
        self.container = ctk.CTkScrollableFrame(self.panel, fg_color="transparent")
        self.container.pack(side="left", fill="both", expand=True, padx=20, pady=10)
        self.widgets = {}

        self.controls_frame = ctk.CTkFrame(self.panel, fg_color="transparent", width=400)
        self.controls_frame.pack(side="right", padx=10, fill="y", pady=5)

        self.tabs = ctk.CTkTabview(self.controls_frame, height=110, fg_color="#111111", segmented_button_selected_color=self.current_theme)
        self.tabs.pack(side="top", fill="x", pady=0)
        self.tabs.add("OSD")
        self.tabs.add("Alerts")
        self.tabs.add("System")
        
        try: self.tabs._segmented_button.configure(text_color=self.current_text_color)
        except: pass

        # --- OSD TAB ---
        osd_top = ctk.CTkFrame(self.tabs.tab("OSD"), fg_color="transparent")
        osd_top.pack(fill="x")
        self.cpu_switch = ctk.CTkSwitch(osd_top, text="CPU", width=40, progress_color=self.current_theme)
        self.cpu_switch.select(); self.cpu_switch.pack(side="left", padx=5)
        self.gpu_switch = ctk.CTkSwitch(osd_top, text="GPU", width=40, progress_color=self.current_theme)
        self.gpu_switch.select(); self.gpu_switch.pack(side="left", padx=5)
        self.ram_switch = ctk.CTkSwitch(osd_top, text="RAM", width=40, progress_color=self.current_theme)
        self.ram_switch.select(); self.ram_switch.pack(side="left", padx=5)
        self.fps_switch = ctk.CTkSwitch(osd_top, text="FPS", width=40, progress_color=self.current_theme)
        self.fps_switch.select(); self.fps_switch.pack(side="left", padx=5)

        osd_bot = ctk.CTkFrame(self.tabs.tab("OSD"), fg_color="transparent")
        osd_bot.pack(fill="x", pady=5)
        ctk.CTkLabel(osd_bot, text="OSD Hotkey: ", font=("Arial", 11)).pack(side="left", padx=5)
        
        self.hotkey_btn = ctk.CTkButton(osd_bot, text=self.config.get("hotkey", "shift+h").upper(), width=100, command=self.start_hotkey_bind, fg_color="#222222", border_color=self.current_theme, border_width=1)
        self.hotkey_btn.pack(side="left", padx=5)

        # --- ALERTS TAB ---
        self.alerts_var = tk.BooleanVar(value=self.config["alerts"])
        self.alerts_switch = ctk.CTkSwitch(self.tabs.tab("Alerts"), text="Enable Thermal Alerts", variable=self.alerts_var, command=self.save_settings, progress_color=self.current_theme)
        self.alerts_switch.pack(anchor="w", pady=2, padx=5)

        self.disable_flash_var = tk.BooleanVar(value=not self.config["animations"])
        self.anim_switch = ctk.CTkSwitch(self.tabs.tab("Alerts"), text="Disable Flashing", variable=self.disable_flash_var, command=self.save_settings, progress_color=self.current_theme)
        self.anim_switch.pack(anchor="w", pady=2, padx=5)

        # --- SYSTEM TAB ---
        sys_f1 = ctk.CTkFrame(self.tabs.tab("System"), fg_color="transparent")
        sys_f1.pack(fill="x")
        self.min_close_var = tk.BooleanVar(value=self.config["min_close"])
        self.min_close_cb = ctk.CTkCheckBox(sys_f1, text="Minimize on Close", variable=self.min_close_var, command=self.save_settings, fg_color=self.current_theme, checkmark_color=self.current_text_color)
        self.min_close_cb.pack(side="left", padx=5, pady=2)

        self.start_min_var = tk.BooleanVar(value=self.config["start_min"])
        self.start_min_cb = ctk.CTkCheckBox(sys_f1, text="Start Minimized", variable=self.start_min_var, command=self.save_settings, fg_color=self.current_theme, checkmark_color=self.current_text_color)
        self.start_min_cb.pack(side="left", padx=5, pady=2)

        sys_f2 = ctk.CTkFrame(self.tabs.tab("System"), fg_color="transparent")
        sys_f2.pack(fill="x")
        self.startup_var = tk.BooleanVar(value=self.config["boot"])
        self.boot_cb = ctk.CTkCheckBox(sys_f2, text="Run on Boot", variable=self.startup_var, command=self.toggle_startup, fg_color=self.current_theme, checkmark_color=self.current_text_color)
        self.boot_cb.pack(side="left", padx=5, pady=2)

        # --- STATIC BOTTOM CONTROLS ---
        self.opacity_slider = ctk.CTkSlider(self.controls_frame, from_=0.1, to=1.0, number_of_steps=100, button_color=self.current_theme, progress_color=self.current_theme, command=self.save_opacity)
        self.opacity_slider.set(self.config["opacity"])
        self.opacity_slider.pack(side="top", pady=5)

        self.actions_frame = ctk.CTkFrame(self.controls_frame, fg_color="transparent")
        self.actions_frame.pack(side="bottom", pady=2)
        
        self.hud_btn = ctk.CTkButton(self.actions_frame, text="LAUNCH OSD", command=self.toggle_hud, font=("Arial", 11, "bold"), fg_color="#111111", border_color="#555555", border_width=1, width=90)
        self.hud_btn.pack(side="left", padx=2)
        self.ram_btn = ctk.CTkButton(self.actions_frame, text="PURGE RAM", command=self.trigger_purge, font=("Arial", 11, "bold"), fg_color="#330000", border_color=self.current_theme, border_width=1, width=90)
        self.ram_btn.pack(side="left", padx=2)
        self.theme_btn = ctk.CTkButton(self.actions_frame, text="THEME", command=self.cycle_theme, font=("Arial", 11, "bold"), fg_color="#111111", border_color=self.current_theme, border_width=1, width=60)
        self.theme_btn.pack(side="left", padx=2)

    def start_hotkey_bind(self):
        self.hotkey_btn.configure(text="LISTENING...", fg_color="#550000")
        threading.Thread(target=self._wait_for_key, daemon=True).start()

    def _wait_for_key(self):
        new_key = keyboard.read_hotkey(suppress=False)
        self.after(0, lambda: self._apply_new_key(new_key))

    def _apply_new_key(self, new_key):
        self.config["hotkey"] = new_key
        self.hotkey_btn.configure(text=new_key.upper(), fg_color="#222222")
        self.save_config()
        self.apply_hotkey()

    def apply_hotkey(self, event=None):
        try:
            keyboard.unhook_all()
            new_key = self.config.get("hotkey", "shift+h").lower()
            keyboard.add_hotkey(new_key, lambda: self.after(0, self.toggle_hud))
            self.hotkey_btn.configure(border_color=self.current_theme)
        except Exception:
            self.hotkey_btn.configure(border_color="#FF0000")

    def save_opacity(self, value):
        self.config["opacity"] = value
        self.save_config()

    def save_settings(self):
        self.config["min_close"] = self.min_close_var.get()
        self.config["start_min"] = self.start_min_var.get()
        self.config["alerts"] = self.alerts_var.get()
        self.config["animations"] = not self.disable_flash_var.get()
        self.save_config()

    # ---------------------------------------------------------
    # METHOD: cycle_theme (Global State Synchronization)
    # Purpose: Iterates through all instantiated UI objects and forces a 
    # .configure() update to sync the entire dashboard to the new hex color.
    # ---------------------------------------------------------

    def cycle_theme(self):
        self.current_theme_idx = (self.current_theme_idx + 1) % len(self.themes)
        self.current_theme = self.themes[self.current_theme_idx]
        self.current_text_color = self.text_colors[self.current_theme_idx]
        self.config["theme_idx"] = self.current_theme_idx
        self.save_config()

        self.panel.configure(border_color=self.current_theme)
        self.tabs.configure(segmented_button_selected_color=self.current_theme)
        try: self.tabs._segmented_button.configure(text_color=self.current_text_color)
        except: pass
        
        self.cpu_switch.configure(progress_color=self.current_theme)
        self.gpu_switch.configure(progress_color=self.current_theme)
        self.ram_switch.configure(progress_color=self.current_theme)
        self.fps_switch.configure(progress_color=self.current_theme)
        self.opacity_slider.configure(button_color=self.current_theme, progress_color=self.current_theme)
        self.ram_btn.configure(border_color=self.current_theme)
        self.theme_btn.configure(border_color=self.current_theme)
        self.hotkey_btn.configure(border_color=self.current_theme)
        
        # SYNC NEW SWITCHES AND CHECKBOXES
        self.alerts_switch.configure(progress_color=self.current_theme)
        self.anim_switch.configure(progress_color=self.current_theme)
        self.min_close_cb.configure(fg_color=self.current_theme, checkmark_color=self.current_text_color)
        self.start_min_cb.configure(fg_color=self.current_theme, checkmark_color=self.current_text_color)
        self.boot_cb.configure(fg_color=self.current_theme, checkmark_color=self.current_text_color)
        
        # FORCED VISUAL REFRESH FOR SSD BARS
        for w_dict in self.widgets.values():
            w_dict["bar"].configure(progress_color=self.current_theme)
            w_dict["bar"].update()
            
        self._finalize_resize()

    def trigger_purge(self):
        if clear_standby_memory():
            self.ram_btn.configure(text="PURGED", fg_color="#005500")
            self.after(2000, lambda: self.ram_btn.configure(text="PURGE RAM", fg_color="#330000"))

    def toggle_hud(self):
        if self.hud_instance is not None and self.hud_instance.winfo_exists():
            self.hud_instance.destroy()
            self.hud_instance = None
            self.hud_btn.configure(text="LAUNCH OSD", border_color="#555555")
        else:
            self.hud_instance = HUDOverlay(self.url, self)
            self.hud_btn.configure(text="CLOSE OSD", border_color=self.current_theme)

    def on_close(self):
        if self.min_close_var.get(): self.iconify()
        else:
            try: self.present_mon.stop()
            except: pass
            keyboard.unhook_all()
            self.destroy()

    def toggle_startup(self):
        self.config["boot"] = self.startup_var.get()
        self.save_config()
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "CoreVanguard"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            if self.startup_var.get(): winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, sys.executable)
            else: winreg.DeleteValue(key, app_name)
            winreg.CloseKey(key)
        except: pass

    def find_sensor_recursive(self, node, keywords):
        text = node.get('Text', '').lower()
        if any(k in text for k in keywords): return node.get('Value')
        for child in node.get('Children', []):
            res = self.find_sensor_recursive(child, keywords)
            if res: return res
        return None
    
    # ---------------------------------------------------------
    # METHOD: check_hw_throttle (Recursive Search Algorithm)
    # Purpose: Recursively digs through the nested LibreHardwareMonitor JSON tree.
    # It searches for hardware-level thermal flags (like "Package Thermal Throttling")
    # regardless of how deep they are buried in the manufacturer's data structure.
    # ---------------------------------------------------------

    def check_hw_throttle(self, node, keywords):
        text = node.get('Text', '').lower()
        val = str(node.get('Value', '')).lower()
        if any(k in text for k in keywords):
            if val in ["yes", "1", "1.0", "100", "100.0", "100%"]: return True
        for child in node.get('Children', []):
            if self.check_hw_throttle(child, keywords): return True
        return False
    
    # ---------------------------------------------------------
    # METHOD: poll_data (Multithreading)
    # Purpose: Runs on a continuous Daemon Thread to fetch JSON web requests.
    # Keeping this off the main UI thread prevents the GUI from freezing 
    # while waiting for network/local server responses.
    # ---------------------------------------------------------

    def poll_data(self):
        while True:
            try:
                data = requests.get(self.url).json()
                self.cpu_throttle_hw, self.gpu_throttle_hw = False, False
                
                for child in data.get('Children', [0])[0].get('Children', []):
                    name = child.get('Text', '').lower()
                    if 'cpu' in name or 'processor' in name:
                        self.cpu_throttle_hw = self.check_hw_throttle(child, ['throttle', 'limit'])
                    elif any(x in name for x in ['gpu', 'nvidia', 'radeon', 'graphics', 'ati']):
                        self.gpu_throttle_hw = self.check_hw_throttle(child, ['throttle', 'limit'])

                for child in data.get('Children', [0])[0].get('Children', []):
                    if any(x in child.get('Text', '').lower() for x in ["drive", "ssd", "hdd"]):
                        name = child['Text']
                        life = self.find_sensor_recursive(child, ["life", "health"]) or "100%"
                        avail = self.find_sensor_recursive(child, ["available", "free", "remaining"]) or "N/A"
                        self._update_row(name, life, avail)

                c_t, c_l = self.cpu.fetch_data()
                g_t, g_l = self.gpu.fetch_data()
                
                self.cpu_gauge.update_data(c_l, c_t, self.cpu_throttle_hw, self.config.get("alerts", True), self.config.get("animations", True))
                self.gpu_gauge.update_data(g_l, g_t, self.gpu_throttle_hw, self.config.get("alerts", True), self.config.get("animations", True))
            except: pass
            time.sleep(2)

    # ---------------------------------------------------------
    # METHOD: _update_row (Dynamic Widget Generation)
    # Purpose: Checks if a storage drive widget exists in the dictionary.
    # If not, it dynamically instantiates a new Progress Bar and Label.
    # If it does, it simply updates the existing objects to save memory.
    # ---------------------------------------------------------

    def _update_row(self, name, life, avail):
        if name not in self.widgets:
            row = ctk.CTkFrame(self.container, fg_color="transparent")
            row.pack(fill="x", pady=4)
            lbl = ctk.CTkLabel(row, text=f"{name} // HP: {life} // FREE: {avail}", font=("Roboto Mono", 13, "bold"), text_color="#FFFFFF")
            lbl.pack(side="left")
            bar = ctk.CTkProgressBar(row, width=280, height=10, progress_color=self.current_theme)
            bar.pack(side="left", padx=15)
            try: bar.set(float(life.replace('%', '').strip()) / 100)
            except: bar.set(1.0)
            
            self.widgets[name] = {"lbl": lbl, "bar": bar}
        else:
            self.widgets[name]["lbl"].configure(text=f"{name} // HP: {life} // FREE: {avail}")

# ==========================================
# MAIN EXECUTION BLOCK
# Instantiates the CoreVanguardEngine object and triggers the 
# infinite Event Loop (mainloop) to listen for user interactions.
# ==========================================

if __name__ == "__main__":
    CoreVanguardEngine().mainloop()