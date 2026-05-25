import PIL.Image
# Pillow 10+ removed ANTIALIAS; patch it back for MoviePy compatibility
if not hasattr(PIL.Image, "ANTIALIAS"):
    try:
        PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS
    except AttributeError:
        PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
# Also ensure LANCZOS alias exists for older MoviePy calls
if not hasattr(PIL.Image, "LANCZOS"):
    PIL.Image.LANCZOS = PIL.Image.Resampling.LANCZOS

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import threading
import os
import re

import traceback
import sys

# --- PyInstaller Metadata Monkeypatch ---
import importlib.metadata
_orig_metadata_version = importlib.metadata.version

def _patched_metadata_version(package_name):
    try:
        return _orig_metadata_version(package_name)
    except importlib.metadata.PackageNotFoundError:
        if package_name == 'imageio':
            return '2.37.3'
        elif package_name == 'imageio_ffmpeg':
            return '0.4.9'
        elif package_name == 'moviepy':
            return '1.0.3'
        elif package_name == 'edge-tts':
            return '6.1.12'
        raise

importlib.metadata.version = _patched_metadata_version
# ----------------------------------------

# --- MoviePy FFMPEG_AudioWriter 'ext' attribute fix ---
from moviepy.audio.io.ffmpeg_audiowriter import FFMPEG_AudioWriter as _FAW
_orig_faw_init = _FAW.__init__

def _patched_faw_init(self, filename, *args, **kwargs):
    _orig_faw_init(self, filename, *args, **kwargs)
    if not hasattr(self, 'ext'):
        self.ext = filename.split('.')[-1]

_FAW.__init__ = _patched_faw_init
# ----------------------------------------

import tts_generator
import video_processor

class SafeTextRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, string):
        self.text_widget.after(0, self._append, string)

    def _append(self, string):
        self.text_widget.configure(state='normal')
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state='disabled')

    def flush(self):
        pass

class VideoEditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Video Birleştirme ve Seslendirme Programı")
        self.root.geometry("750x950")
        self.root.resizable(False, False)
        
        self.video_files = []
        self.custom_audio_file = None
        self.clone_reference_audio = None
        self.bg_audio_enabled = tk.BooleanVar(value=False)
        self.bg_audio_volume = tk.DoubleVar(value=0.2)
        
        self.create_widgets()
        
    def create_widgets(self):
        # Üst Panel (İki sütun)
        main_frame = tk.Frame(self.root, padx=10, pady=5)
        main_frame.pack(fill=tk.X, expand=False)
        
        # Sol Panel (Videolar ve Geçişler)
        left_frame = tk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        tk.Label(left_frame, text="Videolar (Sırasıyla eklenecek)", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        
        self.video_listbox = tk.Listbox(left_frame, width=45, height=14)
        self.video_listbox.pack(pady=5)
        
        btn_frame = tk.Frame(left_frame)
        btn_frame.pack(fill=tk.X)
        
        tk.Button(btn_frame, text="Video Ekle", command=self.add_videos, width=15).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Temizle", command=self.clear_videos, width=15).pack(side=tk.RIGHT, padx=2)
        
        # Geçiş Ayarları
        transition_group = tk.LabelFrame(left_frame, text="Geçiş Ayarları", pady=10, padx=10)
        transition_group.pack(fill=tk.X, pady=15)
        
        tk.Label(transition_group, text="Geçiş Tipi:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.transition_type_var = tk.StringVar(value="none")
        trans_combo = ttk.Combobox(transition_group, textvariable=self.transition_type_var, state="readonly", width=20)
        trans_combo['values'] = ("crossfade", "fade", "none")
        trans_combo.grid(row=0, column=1, sticky=tk.W, pady=5, padx=5)
        
        tk.Label(transition_group, text="Geçiş Süresi (sn):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.transition_var = tk.DoubleVar(value=0.0)
        tk.Spinbox(transition_group, from_=0.0, to=5.0, increment=0.5, textvariable=self.transition_var, width=5).grid(row=1, column=1, sticky=tk.W, pady=5, padx=5)

        # Sağ Panel (Ses İşlemleri)
        right_frame = tk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        tk.Label(right_frame, text="Ses Ayarları", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        
        # Sekmeli Yapı (Notebook)
        self.audio_tabs = ttk.Notebook(right_frame)
        self.audio_tabs.pack(fill=tk.BOTH, expand=False, pady=5)
        
        # Tab 1: Metinden Sese (TTS)
        self.tab_tts = ttk.Frame(self.audio_tabs)
        self.audio_tabs.add(self.tab_tts, text="Metin Gir (Otomatik Ses)")
        
        tk.Label(self.tab_tts, text="Seslendirilecek Metin:\n(ÖNEMLİ: Her video sahnesi arasına bir BOŞ SATIR bırakarak metinleri yazın.\nBıraktığınız boşluk, diğer videoya geçildiği anlamına gelir.)", fg="#d35400").pack(anchor=tk.W, pady=(5, 0), padx=5)
        self.text_area = ScrolledText(self.tab_tts, width=40, height=9, wrap=tk.WORD)
        self.text_area.pack(pady=5, padx=5)
        
        self.voice_frame = tk.Frame(self.tab_tts)
        self.voice_frame.pack(fill=tk.X, pady=5, padx=5)
        tk.Label(self.voice_frame, text="Ses Tonu:").pack(side=tk.LEFT)
        self.voice_var = tk.StringVar(value="tr-TR-AhmetNeural (Türkçe - Erkek)")
        voice_combo = ttk.Combobox(self.voice_frame, textvariable=self.voice_var, state="readonly", width=40)
        voice_combo['values'] = (
            "tr-TR-AhmetNeural (Türkçe - Erkek)",
            "tr-TR-EmelNeural (Türkçe - Kadın)",
            "en-US-ChristopherNeural (İngilizce ABD - Erkek)",
            "en-US-JennyNeural (İngilizce ABD - Kadın)",
            "en-GB-RyanNeural (İngilizce UK - Erkek)",
            "en-GB-SoniaNeural (İngilizce UK - Kadın)",
            "de-DE-KlausNeural (Almanca - Erkek)",
            "de-DE-KatjaNeural (Almanca - Kadın)",
            "fr-FR-HenriNeural (Fransızca - Erkek)",
            "fr-FR-DeniseNeural (Fransızca - Kadın)",
            "es-ES-AlvaroNeural (İspanyolca - Erkek)",
            "es-ES-ElviraNeural (İspanyolca - Kadın)",
            "it-IT-DiegoNeural (İtalyanca - Erkek)",
            "it-IT-ElsaNeural (İtalyanca - Kadın)",
            "ru-RU-DmitryNeural (Rusça - Erkek)",
            "ru-RU-SvetlanaNeural (Rusça - Kadın)",
            "ar-SA-HamedNeural (Arapça - Erkek)",
            "ar-SA-ZariyahNeural (Arapça - Kadın)",
            "ja-JP-KeitaNeural (Japonca - Erkek)",
            "ja-JP-NanamiNeural (Japonca - Kadın)",
            "Kendi Sesimi Klonla (Lokal Yapay Zeka)"
        )
        voice_combo.pack(side=tk.LEFT, padx=5)
        
        # Kendi Sesimi Klonla Çerçevesi (Başlangıçta gizli)
        self.clone_frame = tk.Frame(self.tab_tts)
        tk.Label(self.clone_frame, text="Referans Ses (.wav):").pack(side=tk.LEFT, padx=(5,0))
        tk.Button(self.clone_frame, text="Seç", command=self.select_clone_audio).pack(side=tk.LEFT, padx=5)
        self.lbl_clone_audio = tk.Label(self.clone_frame, text="Yok", fg="blue", wraplength=200)
        self.lbl_clone_audio.pack(side=tk.LEFT)
        
        voice_combo.bind("<<ComboboxSelected>>", self._on_voice_change)
        
        # Konuşma Hızı Seçici
        speed_frame = tk.Frame(self.tab_tts)
        speed_frame.pack(fill=tk.X, pady=2, padx=5)
        tk.Label(speed_frame, text="Konuşma Hızı:").pack(side=tk.LEFT)
        self.tts_rate_var = tk.StringVar(value="Normal (+0%)")
        speed_combo = ttk.Combobox(speed_frame, textvariable=self.tts_rate_var, state="readonly", width=22)
        speed_combo['values'] = (
            "Çok Yavaş (-50%)",
            "Yavaş (-25%)",
            "Normal (+0%)",
            "Hızlı (+25%)",
            "Çok Hızlı (+50%)",
            "Süper Hızlı (+100%)",
        )
        speed_combo.pack(side=tk.LEFT, padx=5)
        
        # Tab 2: Hazır Ses Dosyası
        self.tab_file = ttk.Frame(self.audio_tabs)
        self.audio_tabs.add(self.tab_file, text="Hazır Ses Dosyası Seç")
        
        file_frame = tk.Frame(self.tab_file, pady=20, padx=10)
        file_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(file_frame, text="Eğer kendi kaydettiğiniz bir ses dosyası varsa\nburadan seçebilirsiniz.", justify=tk.CENTER).pack(pady=10)
        
        tk.Button(file_frame, text="Ses Dosyası Seç (.mp3, .wav)", command=self.select_audio_file).pack(pady=10)
        self.lbl_selected_audio = tk.Label(file_frame, text="Seçilen Ses: Yok", fg="blue", wraplength=300)
        self.lbl_selected_audio.pack(pady=10)
        
        tk.Button(file_frame, text="Sesi Temizle", command=self.clear_audio_file).pack(pady=5)
        
        # --- Arka Plan Sesi (Videodan) --- root'a doğrudan bağlı ---
        bg_group = tk.LabelFrame(self.root, text="Arka Plan Sesi (Videodan)", pady=8, padx=10)
        bg_group.pack(fill=tk.X, padx=10, pady=(0, 4))
        
        self.bg_check = tk.Checkbutton(
            bg_group,
            text="Videodaki orijinal arka plan sesini ekle",
            variable=self.bg_audio_enabled,
            command=self._toggle_bg_volume
        )
        self.bg_check.pack(anchor=tk.W)
        
        bg_vol_frame = tk.Frame(bg_group)
        bg_vol_frame.pack(fill=tk.X, pady=(4, 0))
        tk.Label(bg_vol_frame, text="Ses Seviyesi:").pack(side=tk.LEFT)
        self.bg_vol_scale = tk.Scale(
            bg_vol_frame,
            variable=self.bg_audio_volume,
            from_=0.0, to=1.0,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            length=180,
            state=tk.DISABLED
        )
        self.bg_vol_scale.pack(side=tk.LEFT, padx=5)
        self.bg_vol_label = tk.Label(bg_vol_frame, text="(Kapalı)", fg="gray")
        self.bg_vol_label.pack(side=tk.LEFT)
        
        # İşlem Butonu
        self.process_btn = tk.Button(self.root, text="VİDEOYU OLUŞTUR", command=self.start_processing, bg="#2E86C1", fg="white", font=("Arial", 12, "bold"), height=2)
        self.process_btn.pack(fill=tk.X, padx=10, pady=(0, 8))
        
        # Durum Çubuğu ve Log Ekranı Container
        bottom_frame = tk.Frame(self.root, padx=10, pady=5)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, expand=False)
        
        tk.Label(bottom_frame, text="İşlem Kayıtları (Loglar):", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.log_area = ScrolledText(bottom_frame, height=5, state='disabled', bg="#f4f4f4")
        self.log_area.pack(fill=tk.X, expand=False, pady=(0, 5))
        
        self.status_var = tk.StringVar(value="Hazır. Lütfen video ve ses kaynağı ekleyin.")
        self.status_label = tk.Label(bottom_frame, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W, padx=10)
        self.status_label.pack(fill=tk.X)
        
        # Standart çıktıları log ekranına yönlendir (Hataları önlemek ve log göstermek için)
        sys.stdout = SafeTextRedirector(self.log_area)
        sys.stderr = SafeTextRedirector(self.log_area)

    def add_videos(self):
        files = filedialog.askopenfilenames(title="Videoları Seçin", filetypes=(("Video Files", "*.mp4 *.mov *.avi *.mkv"), ("All Files", "*.*")))
        for f in files:
            if f not in self.video_files:
                self.video_files.append(f)
                self.video_listbox.insert(tk.END, os.path.basename(f))
                
    def clear_videos(self):
        self.video_files.clear()
        self.video_listbox.delete(0, tk.END)
        
    def select_audio_file(self):
        f = filedialog.askopenfilename(title="Ses Dosyası Seç", filetypes=(("Audio Files", "*.mp3 *.wav *.m4a"), ("All Files", "*.*")))
        if f:
            self.custom_audio_file = f
            self.lbl_selected_audio.config(text=f"Seçilen Ses: {os.path.basename(f)}")
            
    def clear_audio_file(self):
        self.custom_audio_file = None
        self.lbl_selected_audio.config(text="Seçilen Ses: Yok")
        
    def select_clone_audio(self):
        f = filedialog.askopenfilename(title="Klonlanacak Referans Sesi Seç", filetypes=(("WAV Files", "*.wav"), ("All Files", "*.*")))
        if f:
            self.clone_reference_audio = f
            self.lbl_clone_audio.config(text=os.path.basename(f))

    def _on_voice_change(self, event=None):
        if self.voice_var.get() == "Kendi Sesimi Klonla (Lokal Yapay Zeka)":
            self.clone_frame.pack(fill=tk.X, pady=2, padx=5, after=self.voice_frame)
        else:
            self.clone_frame.pack_forget()
    
    def _toggle_bg_volume(self):
        if self.bg_audio_enabled.get():
            self.bg_vol_scale.config(state=tk.NORMAL)
            self.bg_vol_label.config(text="(Açık)", fg="#27ae60")
        else:
            self.bg_vol_scale.config(state=tk.DISABLED)
            self.bg_vol_label.config(text="(Kapalı)", fg="gray")
        
    def start_processing(self):
        if not self.video_files:
            messagebox.showwarning("Uyarı", "Lütfen en az bir video ekleyin!")
            return
            
        current_tab_index = self.audio_tabs.index(self.audio_tabs.select())
        text = self.text_area.get("1.0", tk.END).strip()
        
        # Tab 0 ise TTS, Tab 1 ise Custom Audio
        if current_tab_index == 0:
            if not text:
                messagebox.showwarning("Uyarı", "Lütfen seslendirilecek metni girin!")
                return
            use_tts = True
            
            if self.voice_var.get() == "Kendi Sesimi Klonla (Lokal Yapay Zeka)" and not self.clone_reference_audio:
                messagebox.showwarning("Uyarı", "Ses klonlama seçildi ama referans ses (wav) seçilmedi!")
                return
            
            lines = [scene.strip() for scene in re.split(r'\n\s*\n', text.strip()) if scene.strip()]
            if len(lines) != len(self.video_files):
                messagebox.showerror("Hata", f"Uyumsuzluk Tespit Edildi!\n\nEklenen video sayısı: {len(self.video_files)}\nMetin sahne sayısı: {len(lines)}\n\nLütfen her video metni arasında boş bir satır bırakarak sayıları eşitleyin.")
                return
            else:
                if not messagebox.askyesno("Onay", f"Harika! {len(self.video_files)} video ve {len(lines)} sahne metni eşleşti.\n\nİşleme başlamak istiyor musunuz?"):
                    return
        else:
            if not self.custom_audio_file:
                messagebox.showwarning("Uyarı", "Lütfen bir ses dosyası seçin!")
                return
            use_tts = False
            
        output_file = filedialog.asksaveasfilename(defaultextension=".mp4", initialfile="sonuc_video.mp4", title="Kaydedilecek Yeri Seçin", filetypes=(("MP4 Video", "*.mp4"),))
        if not output_file:
            return
            
        self.process_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.process_task, args=(text, output_file, use_tts), daemon=True).start()

    def process_task(self, text, output_file, use_tts):
        try:
            audio_to_use = None
            temp_audios = []
            # Geçici dosyaları çıktı videosunun bulunduğu klasöre kaydet
            temp_dir = os.path.dirname(output_file)
            
            if use_tts:
                self.status_var.set("Adım 1/2: Ses dosyaları üretiliyor (TTS)...")
                voice_code = self.voice_var.get().split(" ")[0]
                # Seçilen hız etiketinden yüzde değerini çıkar (örn. "Hızlı (+25%)" → "+25%")
                speed_label = self.tts_rate_var.get()
                import re as _re
                _rate_match = _re.search(r'([+-]\d+%)', speed_label)
                tts_rate = _rate_match.group(1) if _rate_match else "+0%"
                
                is_clone = (self.voice_var.get() == "Kendi Sesimi Klonla (Lokal Yapay Zeka)")
                ref_audio = self.clone_reference_audio if is_clone else None
                
                lines = [scene.strip() for scene in re.split(r'\n\s*\n', text.strip()) if scene.strip()]
                
                if len(lines) == 1 and len(self.video_files) > 1:
                    temp_audio = os.path.join(temp_dir, "temp_voiceover_single.mp3")
                    if is_clone:
                        temp_audio = os.path.join(temp_dir, "temp_voiceover_single.wav")
                    tts_generator.generate_audio(lines[0], temp_audio, voice=voice_code, rate=tts_rate, reference_audio=ref_audio)
                    audio_to_use = temp_audio
                    temp_audios.append(temp_audio)
                else:
                    audio_to_use = []
                    for i in range(len(self.video_files)):
                        if i < len(lines):
                            temp_audio = os.path.join(temp_dir, f"temp_voiceover_{i}.mp3")
                            if is_clone:
                                temp_audio = os.path.join(temp_dir, f"temp_voiceover_{i}.wav")
                            tts_generator.generate_audio(lines[i], temp_audio, voice=voice_code, rate=tts_rate, reference_audio=ref_audio)
                            audio_to_use.append(temp_audio)
                            temp_audios.append(temp_audio)
            else:
                self.status_var.set("Adım 1/2: Hazır ses dosyası ayarlanıyor...")
                audio_to_use = self.custom_audio_file
                
            self.status_var.set("Adım 2/2: Videolar birleştiriliyor. Bu işlem bilgisayar hızına göre vakit alabilir...")
            
            transition_duration = self.transition_var.get()
            transition_type = self.transition_type_var.get()
            bg_volume = self.bg_audio_volume.get() if self.bg_audio_enabled.get() else 0.0
            
            video_processor.process_video(
                self.video_files, 
                audio_to_use, 
                output_file, 
                transition_duration=transition_duration,
                transition_type=transition_type,
                bg_audio_volume=bg_volume
            )
            
            if use_tts:
                for temp_audio in temp_audios:
                    if os.path.exists(temp_audio):
                        try:
                            os.remove(temp_audio)
                        except Exception as e:
                            print(f"Geçici dosya silinemedi {temp_audio}: {e}")
                
            self.status_var.set("İşlem Başarılı! Video kaydedildi.")
            messagebox.showinfo("Başarılı", f"Video başarıyla oluşturuldu!\n\nKonum: {output_file}")
            
        except Exception as e:
            self.status_var.set("Hata oluştu!")
            print("\n--- BİR HATA OLUŞTU ---")
            traceback.print_exc(file=sys.stdout)
            messagebox.showerror("Hata", f"İşlem sırasında bir hata oluştu:\n{str(e)}\n\nDetaylar için lütfen alttaki Log ekranını inceleyin.")
            
        finally:
            self.process_btn.config(state=tk.NORMAL)

if __name__ == "__main__":
    root = tk.Tk()
    app = VideoEditorApp(root)
    root.mainloop()
