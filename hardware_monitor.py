import time
import requests 
import matplotlib 
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt

# ==========================================
# 1. BASE CLASS (Abstraction & Universal Logic)
# ==========================================
class HardwareSensor:
    def __init__(self, name, url):
        self.name = name
        self.url = url
        self.temp_history = []
        self.load_history = []

    def _find_hardware_branch(self, data, hardware_keywords):
        """Finds the main branch for the CPU or GPU based on icon/id."""
        image_url = data.get("ImageURL", "").lower()
        hw_id = data.get("HardwareId", "").lower()
        
        # Check if this node is the hardware we are looking for
        if any(kw in image_url or kw in hw_id for kw in hardware_keywords):
            return data

        # Otherwise, keep digging down the tree
        for child in data.get("Children", []):
            result = self._find_hardware_branch(child, hardware_keywords)
            if result:
                return result
        return None

    def _get_all_sensors(self, data, sensor_list):
        """Flattens ONLY the isolated hardware branch into a simple list."""
        if "Value" in data and data["Value"] != "":
            sensor_list.append({
                "Text": data.get("Text"),
                "Value": data.get("Value")
            })
        for child in data.get("Children", []):
            self._get_all_sensors(child, sensor_list)

    def fetch_dynamic_data(self, hw_keywords, priority_list, target_unit):
        try:
            raw_json = requests.get(self.url, timeout=2).json()
            
            # 1. Isolate the specific hardware (CPU or GPU)
            hw_branch = self._find_hardware_branch(raw_json, hw_keywords)
            if not hw_branch:
                return "0"

            # 2. Flatten only this branch so we don't mix up CPU and GPU sensors
            branch_sensors = []
            self._get_all_sensors(hw_branch, branch_sensors)
            
            # 3. Priority Search: Find the best matching sensor name
            for name in priority_list:
                for s in branch_sensors:
                    if s["Text"] == name and target_unit in s["Value"]:
                        return s["Value"]
            return "0"
        except:
            return "0"

    def log_current_state(self, temp_str, load_str):
        try:
            t = float(temp_str.split()[0]) if temp_str and " " in temp_str else 0.0
            l = float(load_str.split()[0]) if load_str and " " in load_str else 0.0
            self.temp_history.append(t)
            self.load_history.append(l)
            return t, l
        except:
            self.temp_history.append(0.0)
            self.load_history.append(0.0)
            return 0.0, 0.0

# ==========================================
# 2. DERIVED CLASSES (Universal Detection)
# ==========================================
class CPUSensor(HardwareSensor):
    def fetch_data(self):
        # Universal Keywords to find any CPU
        hw_keywords = ["cpu"] 
        
        # Priority list (AMD Ryzen often uses Tctl/Tdie, Intel uses Package)
        temps = ["CPU Package", "Core Max", "CPU (Tctl/Tdie)", "CPU Core", "Temperature"]
        loads = ["CPU Total", "Total"]
        
        t_val = self.fetch_dynamic_data(hw_keywords, temps, "°C")
        l_val = self.fetch_dynamic_data(hw_keywords, loads, "%")
        return self.log_current_state(t_val, l_val)

class GPUSensor(HardwareSensor):
    def fetch_data(self):
        hw_keywords = ["nvidia", "amd", "gpu"] 
        
        # Priority list for dedicated and integrated GPUs
        temps = ["GPU Core", "GPU Hot Spot", "GPU Package", "Temperature"]
        loads = ["GPU Core", "D3D 3D", "GPU Memory", "Load"]
        
        # 1. Fetch GPU Load and attempt to fetch dedicated GPU Temp
        t_val = self.fetch_dynamic_data(hw_keywords, temps, "°C")
        l_val = self.fetch_dynamic_data(hw_keywords, loads, "%")
        
        # 2. THE FALLBACK: If GPU has no thermal sensor (Integrated Graphics), borrow the CPU's temp
        if t_val == "0" or t_val == 0.0:
            t_val = self.fetch_dynamic_data(["cpu"], ["CPU Package", "Core Max", "Temperature"], "°C")
            
        return self.log_current_state(t_val, l_val)
    
class StorageSensor(HardwareSensor):
    def fetch_data(self):
        # Keywords to find any SSD, NVMe, or HDD branch
        hw_keywords = ["ssd", "nvme", "hdd"] 
        
        # Priority lists for storage metrics
        temps = ["Temperature"]
        health = ["Life", "Remaining Life", "Health"]
        usage = ["Used Space", "Load"]
        
        # Fetch dynamic data
        temp_val = self.fetch_dynamic_data(hw_keywords, temps, "°C")
        life_val = self.fetch_dynamic_data(hw_keywords, health, "%")
        used_val = self.fetch_dynamic_data(hw_keywords, usage, "%")
        
        # Clean up the strings into floats
        try:
            t = float(temp_val.split()[0]) if temp_val and " " in temp_val else 0.0
            l = float(life_val.split()[0]) if life_val and " " in life_val else 0.0
            u = float(used_val.split()[0]) if used_val and " " in used_val else 0.0
            return t, l, u
        except:
            return 0.0, 0.0, 0.0

# ==========================================
# 3. MANAGER CLASS (Aggregation & Logic)
# ==========================================
class SessionLogger:
    def __init__(self, duration, interval):
        self.duration = duration
        self.interval = interval
        self.time_stamps = []
        
        # 1. Define the URL FIRST
        self.url = "http://localhost:8085/data.json"
        
        # 2. Test the connection
        try:
            requests.get(self.url, timeout=2)
            print("[OK] Connected to LibreHardwareMonitor Web Server.")
        except Exception as e:
            print(f"[ERROR] Connection Failed:{e}")
            print("Make sure 'Remote Web Server -> Run' is checked in LHM.")
            exit(1)

        # 3. NOW create the sensors (since self.url exists)
        self.cpu = CPUSensor("Processor", self.url)
        self.gpu = GPUSensor("Graphics Card", self.url)
        self.storage = StorageSensor("System Drive", self.url)

    def run_diagnostic(self):
        print(f"--- Starting {self.duration}-Second Hardware Diagnostic ---")
        iterations = int(self.duration / self.interval)
        
        for i in range(iterations):
            current_time = i * self.interval
            self.time_stamps.append(current_time)
            
            # Fetch data for all three hardware components
            cpu_temp, cpu_load = self.cpu.fetch_data()
            gpu_temp, gpu_load = self.gpu.fetch_data()
            ssd_temp, ssd_life, ssd_used = self.storage.fetch_data()
            
            if cpu_temp == 0 and cpu_load == 0:
                print("DEBUG: Logic failed to find sensor values. Check sensor names.")

            # Updated print statement to include the SSD stats
            print(f"Time: {current_time}s | CPU: {cpu_temp}°C ({cpu_load}%) | GPU: {gpu_temp}°C ({gpu_load}%) | SSD: {ssd_temp}°C (Health: {ssd_life}%)")
            time.sleep(self.interval)

    def plot_results(self):
        print("DEBUG: Entering plot_results function...")
        try:
            plt.style.use('dark_background')
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

            ax1.plot(self.time_stamps, self.cpu.temp_history, label='CPU Temp (°C)', color='cyan')
            ax1.plot(self.time_stamps, self.gpu.temp_history, label='GPU Temp (°C)', color='magenta')
            ax1.set_title('Universal Hardware Thermal Performance')
            ax1.legend()

            ax2.plot(self.time_stamps, self.cpu.load_history, label='CPU Load (%)', color='cyan', linestyle='--')
            ax2.plot(self.time_stamps, self.gpu.load_history, label='GPU Load (%)', color='magenta', linestyle='--')
            ax2.set_title('Hardware Utilization')
            ax2.set_ylim(0, 105)
            ax2.legend()

            plt.tight_layout()
            
            save_path = "hardware_report.png"
            print(f"DEBUG: Attempting to save graph to: {save_path}")
            plt.savefig(save_path)
            print("SUCCESS: Graph saved successfully!")
            
            print("DEBUG: Attempting to open window (plt.show)...")
            plt.show()
            print("DEBUG: plt.show() finished.")
            
        except Exception as e:
            print(f"CRITICAL ERROR in plot_results: {e}")

# ==========================================
# 4. MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    logger = SessionLogger(duration=30, interval=2)
    logger.run_diagnostic()
    logger.plot_results()