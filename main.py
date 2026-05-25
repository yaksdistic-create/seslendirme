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
        w = self.text_widget
        w.configure(state='normal')
        # Windows satır sonlarını sadeleştir
        string = string.replace('\r\n', '\n')
        # tqdm gibi araçlar ilerlemeyi '\r' (satır başı) ile aynı satırda günceller.
        # Bu karakterleri işleyerek ilerleme çubuğunu üst üste yığmak yerine tek
        # satırda güncelliyoruz (aksi halde log şişer, bellek/CPU harcar, arayüz yavaşlar).
        for token in re.split('([\r\n])', string):
            if token == '':
                continue
            if token == '\n':
                w.insert(tk.END, '\n')
            elif token == '\r':
                # Satır başına dön: mevcut (son) satırın içeriğini sil
                w.delete('end-1c linestart', 'end-1c')
            else:
                w.insert(tk.END, token)
        w.see(tk.END)
        w.configure(state='disabled')

    def flush(self):
        pass

class VideoEditorApp:
    # --- Renk paleti ve yazı tipleri (tutarlı modern görünüm) ---
    COLORS = {
        "bg": "#eef1f8",          # uygulama arka planı
        "card": "#ffffff",        # panel/kart arka planı
        "accent": "#4f46e5",      # ana vurgu (indigo)
        "accent_active": "#4338ca",
        "accent_soft": "#eceefc", # hafif vurgu (sekme/ikincil buton)
        "text": "#1f2933",        # ana metin
        "muted": "#6b7280",       # ikincil metin
        "border": "#dfe3ee",      # kenarlık
        "success": "#16a34a",
        "warn": "#d97706",
        "danger_bg": "#fee2e2",
        "danger_fg": "#b91c1c",
        "log_bg": "#1e1e2e",      # koyu konsol arka planı
        "log_fg": "#cdd6f4",
        "header": "#312e81",      # başlık çubuğu (koyu indigo)
    }
    FONT = ("Segoe UI", 10)
    FONT_BOLD = ("Segoe UI", 10, "bold")
    FONT_H = ("Segoe UI", 11, "bold")
    FONT_MONO = ("Consolas", 9)

    def __init__(self, root):
        self.root = root
        self.root.title("Video Birleştirme ve Seslendirme Stüdyosu")
        self.root.geometry("860x1000")
        self.root.minsize(820, 900)
        self.root.configure(bg=self.COLORS["bg"])

        self.video_files = []
        self.custom_audio_file = None
        self.clone_reference_audio = None
        self.bg_audio_enabled = tk.BooleanVar(value=False)
        self.bg_audio_volume = tk.DoubleVar(value=0.2)
        # Süre eşitleme: açıkken video seslendirmeye göre ayarlanir (dondur/kırp)
        self.sync_to_audio_enabled = tk.BooleanVar(value=True)

        # Standart çıktıların orijinallerini sakla (kapanışta geri yüklenecek)
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

        self._setup_style()
        self.create_widgets()

        # Pencere kapatılırken çıktı akışlarını geri yükle
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        # Tk'yi kapatmadan önce stdout/stderr'i eski haline getir ki
        # kapanış sırasında oluşabilecek hatalar yok edilmiş widget'a yazılmasın.
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        self.root.destroy()

    # --- Thread güvenli UI yardımcıları ---
    # Tkinter thread-safe değildir; arka plan iş parçacığından gelen tüm
    # arayüz güncellemeleri ana iş parçacığına root.after ile aktarılır.
    def _set_status(self, text):
        self.root.after(0, self.status_var.set, text)

    def _show_message(self, kind, title, msg):
        self.root.after(0, lambda: kind(title, msg))

    def _set_process_btn_state(self, state):
        self.root.after(0, self.process_btn.config, {"state": state})

    # --- Görsel tema kurulumu ---
    def _setup_style(self):
        c = self.COLORS
        self.root.option_add("*Font", self.FONT)
        # Combobox açılır listesinin görünümü
        self.root.option_add("*TCombobox*Listbox.background", c["card"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Sekmeli yapı (Notebook)
        style.configure("TNotebook", background=c["bg"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=c["accent_soft"], foreground=c["muted"],
            padding=(18, 9), font=self.FONT_BOLD, borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", c["card"])],
            foreground=[("selected", c["accent"])],
        )
        # Sekme içerikleri (ttk.Frame) kart rengini alsın
        style.configure("TFrame", background=c["card"])

        # Açılır kutular (Combobox)
        style.configure(
            "TCombobox",
            fieldbackground=c["card"], background=c["card"],
            foreground=c["text"], arrowcolor=c["accent"],
            bordercolor=c["border"], lightcolor=c["border"],
            darkcolor=c["border"], padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["card"])],
            selectbackground=[("readonly", c["card"])],
            selectforeground=[("readonly", c["text"])],
        )

    # --- Yardımcı: kart çerçevesi ---
    def _card(self, parent, **kw):
        c = self.COLORS
        return tk.Frame(
            parent, bg=c["card"], highlightbackground=c["border"],
            highlightcolor=c["border"], highlightthickness=1, bd=0, **kw
        )

    # --- Yardımcı: stilize buton ---
    def _make_button(self, parent, text, command, kind="secondary", **kw):
        c = self.COLORS
        if kind == "primary":
            bg, fg, abg = c["accent"], "#ffffff", c["accent_active"]
            font = ("Segoe UI", 12, "bold")
        elif kind == "danger":
            bg, fg, abg = c["danger_bg"], c["danger_fg"], "#fecaca"
            font = self.FONT_BOLD
        else:  # secondary
            bg, fg, abg = c["accent_soft"], c["accent"], "#e0e3fb"
            font = self.FONT_BOLD
        return tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=abg, activeforeground=fg, relief="flat",
            bd=0, cursor="hand2", font=font, padx=14, pady=7, **kw
        )

    # --- Yardımcı: bölüm başlığı ---
    def _section_title(self, parent, text):
        c = self.COLORS
        return tk.Label(parent, text=text, bg=c["card"], fg=c["accent"], font=self.FONT_H)

    def create_widgets(self):
        c = self.COLORS

        # ---- Üst Başlık Çubuğu ----
        header = tk.Frame(self.root, bg=c["header"])
        header.pack(fill=tk.X)
        tk.Label(
            header, text="🎬  Video Birleştirme ve Seslendirme Stüdyosu",
            bg=c["header"], fg="#ffffff", font=("Segoe UI", 15, "bold"),
            padx=18, anchor=tk.W,
        ).pack(fill=tk.X, pady=(12, 0))
        tk.Label(
            header, text="Videolarını birleştir, otomatik seslendirme ekle ve tek tıkla dışa aktar.",
            bg=c["header"], fg="#c7c9f5", font=("Segoe UI", 9),
            padx=18, anchor=tk.W,
        ).pack(fill=tk.X, pady=(0, 12))

        # ---- İçerik Alanı ----
        outer = tk.Frame(self.root, bg=c["bg"], padx=14, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)

        # Üst Panel (İki sütun)
        main_frame = tk.Frame(outer, bg=c["bg"])
        main_frame.pack(fill=tk.X, expand=False)

        # ===== Sol Panel (Videolar ve Geçişler) =====
        left_card = self._card(main_frame, padx=14, pady=12)
        left_card.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))

        self._section_title(left_card, "Videolar  (sırasıyla eklenecek)").pack(anchor=tk.W, pady=(0, 8))

        self.video_listbox = tk.Listbox(
            left_card, width=42, height=9, font=self.FONT,
            bg="#fbfbfe", fg=c["text"], relief="flat", bd=0,
            highlightthickness=1, highlightbackground=c["border"],
            selectbackground=c["accent"], selectforeground="#ffffff",
            activestyle="none",
        )
        self.video_listbox.pack(pady=(0, 10))

        btn_frame = tk.Frame(left_card, bg=c["card"])
        btn_frame.pack(fill=tk.X)
        self._make_button(btn_frame, "+ Video Ekle", self.add_videos, kind="secondary").pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        self._make_button(btn_frame, "Temizle", self.clear_videos, kind="danger").pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(4, 0))

        # Geçiş Ayarları
        transition_group = tk.LabelFrame(
            left_card, text=" Geçiş Ayarları ", bg=c["card"], fg=c["accent"],
            font=self.FONT_BOLD, bd=1, relief="solid", padx=12, pady=10,
            highlightbackground=c["border"],
        )
        transition_group.pack(fill=tk.X, pady=(16, 0))

        tk.Label(transition_group, text="Geçiş Tipi:", bg=c["card"], fg=c["text"]).grid(row=0, column=0, sticky=tk.W, pady=6)
        self.transition_type_var = tk.StringVar(value="none")
        trans_combo = ttk.Combobox(transition_group, textvariable=self.transition_type_var, state="readonly", width=18)
        trans_combo['values'] = ("crossfade", "fade", "none")
        trans_combo.grid(row=0, column=1, sticky=tk.W, pady=6, padx=6)

        tk.Label(transition_group, text="Geçiş Süresi (sn):", bg=c["card"], fg=c["text"]).grid(row=1, column=0, sticky=tk.W, pady=6)
        self.transition_var = tk.DoubleVar(value=0.0)
        tk.Spinbox(
            transition_group, from_=0.0, to=5.0, increment=0.5,
            textvariable=self.transition_var, width=6, font=self.FONT,
            relief="flat", bd=0, highlightthickness=1, highlightbackground=c["border"],
            buttonbackground=c["accent_soft"],
        ).grid(row=1, column=1, sticky=tk.W, pady=6, padx=6)

        # ===== Sağ Panel (Ses İşlemleri) =====
        right_card = self._card(main_frame, padx=14, pady=12)
        right_card.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._section_title(right_card, "Ses Ayarları").pack(anchor=tk.W, pady=(0, 8))

        # Sekmeli Yapı (Notebook)
        self.audio_tabs = ttk.Notebook(right_card)
        self.audio_tabs.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Metinden Sese (TTS)
        self.tab_tts = ttk.Frame(self.audio_tabs, padding=12)
        self.audio_tabs.add(self.tab_tts, text="Metin Gir (Otomatik Ses)")

        tk.Label(
            self.tab_tts,
            text="Seslendirilecek Metin\nÖNEMLİ: Her video sahnesi arasına bir BOŞ SATIR bırakın.\nBıraktığınız boşluk, diğer videoya geçildiği anlamına gelir.",
            fg=c["warn"], bg=c["card"], justify=tk.LEFT, font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(0, 6))
        self.text_area = ScrolledText(
            self.tab_tts, width=42, height=6, wrap=tk.WORD, font=self.FONT,
            bg="#fbfbfe", fg=c["text"], relief="flat", bd=0,
            highlightthickness=1, highlightbackground=c["border"],
            insertbackground=c["accent"], padx=8, pady=8,
        )
        self.text_area.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self.voice_frame = tk.Frame(self.tab_tts, bg=c["card"])
        self.voice_frame.pack(fill=tk.X, pady=4)
        tk.Label(self.voice_frame, text="Ses Tonu:", bg=c["card"], fg=c["text"]).pack(side=tk.LEFT)
        self.voice_var = tk.StringVar(value="tr-TR-AhmetNeural (Türkçe - Erkek)")
        voice_combo = ttk.Combobox(self.voice_frame, textvariable=self.voice_var, state="readonly", width=38)
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
        voice_combo.pack(side=tk.LEFT, padx=6)

        # Kendi Sesimi Klonla Çerçevesi (Başlangıçta gizli)
        self.clone_frame = tk.Frame(self.tab_tts, bg=c["card"])
        tk.Label(self.clone_frame, text="Referans Ses (.wav):", bg=c["card"], fg=c["text"]).pack(side=tk.LEFT, padx=(0, 4))
        self._make_button(self.clone_frame, "Seç", self.select_clone_audio, kind="secondary").pack(side=tk.LEFT, padx=4)
        self.lbl_clone_audio = tk.Label(self.clone_frame, text="Yok", fg=c["accent"], bg=c["card"], wraplength=200)
        self.lbl_clone_audio.pack(side=tk.LEFT)

        # Klon Dili Çerçevesi (Sadece klonlama seçiliyken görünür)
        # Edge-TTS seslerinin dili kendi adında gömülüdür; bu seçim yalnızca
        # "Kendi Sesimi Klonla" (XTTS) için geçerlidir.
        self.clone_lang_frame = tk.Frame(self.tab_tts, bg=c["card"])
        tk.Label(self.clone_lang_frame, text="Klon Dili:", bg=c["card"], fg=c["text"]).pack(side=tk.LEFT, padx=(0, 4))
        self.clone_lang_var = tk.StringVar(value="Türkçe (tr)")
        clone_lang_combo = ttk.Combobox(self.clone_lang_frame, textvariable=self.clone_lang_var, state="readonly", width=18)
        clone_lang_combo['values'] = ("Türkçe (tr)", "İngilizce (en)")
        clone_lang_combo.pack(side=tk.LEFT, padx=6)

        voice_combo.bind("<<ComboboxSelected>>", self._on_voice_change)

        # Konuşma Hızı Seçici
        speed_frame = tk.Frame(self.tab_tts, bg=c["card"])
        speed_frame.pack(fill=tk.X, pady=4)
        tk.Label(speed_frame, text="Konuşma Hızı:", bg=c["card"], fg=c["text"]).pack(side=tk.LEFT)
        self.tts_rate_var = tk.StringVar(value="Normal (+0%)")
        speed_combo = ttk.Combobox(speed_frame, textvariable=self.tts_rate_var, state="readonly", width=20)
        speed_combo['values'] = (
            "Çok Yavaş (-50%)",
            "Yavaş (-25%)",
            "Normal (+0%)",
            "Hızlı (+25%)",
            "Çok Hızlı (+50%)",
            "Süper Hızlı (+100%)",
        )
        speed_combo.pack(side=tk.LEFT, padx=6)

        # Tab 2: Hazır Ses Dosyası
        self.tab_file = ttk.Frame(self.audio_tabs, padding=12)
        self.audio_tabs.add(self.tab_file, text="Hazır Ses Dosyası Seç")

        file_frame = tk.Frame(self.tab_file, bg=c["card"], pady=10)
        file_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            file_frame,
            text="Eğer kendi kaydettiğiniz bir ses dosyası varsa\nburadan seçebilirsiniz.",
            justify=tk.CENTER, bg=c["card"], fg=c["muted"],
        ).pack(pady=10)

        self._make_button(file_frame, "Ses Dosyası Seç (.mp3, .wav)", self.select_audio_file, kind="secondary").pack(pady=8)
        self.lbl_selected_audio = tk.Label(file_frame, text="Seçilen Ses: Yok", fg=c["accent"], bg=c["card"], wraplength=300)
        self.lbl_selected_audio.pack(pady=8)

        self._make_button(file_frame, "Sesi Temizle", self.clear_audio_file, kind="danger").pack(pady=6)

        # ===== Arka Plan Sesi (Videodan) =====
        bg_group = tk.LabelFrame(
            outer, text=" Arka Plan Sesi (Videodan) ", bg=c["card"], fg=c["accent"],
            font=self.FONT_BOLD, bd=1, relief="solid", padx=12, pady=10,
            highlightbackground=c["border"],
        )
        bg_group.pack(fill=tk.X, pady=(10, 0))

        self.bg_check = tk.Checkbutton(
            bg_group,
            text="Videodaki orijinal arka plan sesini ekle",
            variable=self.bg_audio_enabled,
            command=self._toggle_bg_volume,
            bg=c["card"], fg=c["text"], activebackground=c["card"],
            activeforeground=c["text"], selectcolor=c["card"], font=self.FONT,
            cursor="hand2",
        )
        self.bg_check.pack(anchor=tk.W)

        bg_vol_frame = tk.Frame(bg_group, bg=c["card"])
        bg_vol_frame.pack(fill=tk.X, pady=(6, 0))
        tk.Label(bg_vol_frame, text="Ses Seviyesi:", bg=c["card"], fg=c["text"]).pack(side=tk.LEFT)
        self.bg_vol_scale = tk.Scale(
            bg_vol_frame,
            variable=self.bg_audio_volume,
            from_=0.0, to=1.0,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            length=200,
            state=tk.DISABLED,
            bg=c["card"], fg=c["text"], troughcolor=c["accent_soft"],
            highlightthickness=0, activebackground=c["accent"], bd=0,
        )
        self.bg_vol_scale.pack(side=tk.LEFT, padx=6)
        self.bg_vol_label = tk.Label(bg_vol_frame, text="(Kapalı)", fg=c["muted"], bg=c["card"])
        self.bg_vol_label.pack(side=tk.LEFT)

        # ===== Video / Ses Süre Eşitleme =====
        sync_group = tk.LabelFrame(
            outer, text=" Video / Ses Süresi ", bg=c["card"], fg=c["accent"],
            font=self.FONT_BOLD, bd=1, relief="solid", padx=12, pady=10,
            highlightbackground=c["border"],
        )
        sync_group.pack(fill=tk.X, pady=(10, 0))

        self.sync_check = tk.Checkbutton(
            sync_group,
            text="Videoyu seslendirme süresine göre ayarla",
            variable=self.sync_to_audio_enabled,
            bg=c["card"], fg=c["text"], activebackground=c["card"],
            activeforeground=c["text"], selectcolor=c["card"], font=self.FONT,
            cursor="hand2",
        )
        self.sync_check.pack(anchor=tk.W)
        tk.Label(
            sync_group,
            text=("Açık: seslendirme videodan uzunsa son kare donar, kısaysa video kesilir.\n"
                  "Kapalı: videolar orijinal süresinde kalır, seslendirme üzerine bindirilir."),
            bg=c["card"], fg=c["muted"], justify=tk.LEFT, font=("Segoe UI", 8),
        ).pack(anchor=tk.W, pady=(2, 0))

        # ===== İşlem Butonu =====
        self.process_btn = self._make_button(outer, "VİDEOYU OLUŞTUR", self.start_processing, kind="primary")
        self.process_btn.configure(pady=12)
        self.process_btn.pack(fill=tk.X, pady=(10, 0))

        # ===== Durum Çubuğu ve Log Ekranı =====
        log_header = tk.Frame(outer, bg=c["bg"])
        log_header.pack(fill=tk.X, pady=(10, 4))
        tk.Label(log_header, text="İşlem Kayıtları (Loglar)", bg=c["bg"], fg=c["muted"], font=self.FONT_BOLD).pack(anchor=tk.W)

        self.log_area = ScrolledText(
            outer, height=16, state='disabled', bg=c["log_bg"], fg=c["log_fg"],
            relief="flat", bd=0, highlightthickness=1, highlightbackground=c["border"],
            font=self.FONT_MONO, padx=10, pady=8, insertbackground=c["log_fg"],
        )
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self.status_var = tk.StringVar(value="Hazır. Lütfen video ve ses kaynağı ekleyin.")
        self.status_label = tk.Label(
            outer, textvariable=self.status_var, bg=c["card"], fg=c["text"],
            anchor=tk.W, padx=12, pady=8, font=self.FONT,
            relief="flat", bd=0, highlightthickness=1, highlightbackground=c["border"],
        )
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
            self.clone_frame.pack(fill=tk.X, pady=4, after=self.voice_frame)
            self.clone_lang_frame.pack(fill=tk.X, pady=4, after=self.clone_frame)
        else:
            self.clone_frame.pack_forget()
            self.clone_lang_frame.pack_forget()

    def _toggle_bg_volume(self):
        if self.bg_audio_enabled.get():
            self.bg_vol_scale.config(state=tk.NORMAL)
            self.bg_vol_label.config(text="(Açık)", fg=self.COLORS["success"])
        else:
            self.bg_vol_scale.config(state=tk.DISABLED)
            self.bg_vol_label.config(text="(Kapalı)", fg=self.COLORS["muted"])

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
            # Geçici dosyaları çıktı videosunun bulunduğu klasöre kaydet.
            # dirname boş dönerse (yol klasör içermiyorsa) çalışma dizinine düş.
            temp_dir = os.path.dirname(output_file) or os.getcwd()

            if use_tts:
                self._set_status("Adım 1/2: Ses dosyaları üretiliyor (TTS)...")
                voice_code = self.voice_var.get().split(" ")[0]
                # Seçilen hız etiketinden yüzde değerini çıkar (örn. "Hızlı (+25%)" → "+25%")
                speed_label = self.tts_rate_var.get()
                _rate_match = re.search(r'([+-]\d+%)', speed_label)
                tts_rate = _rate_match.group(1) if _rate_match else "+0%"

                is_clone = (self.voice_var.get() == "Kendi Sesimi Klonla (Lokal Yapay Zeka)")
                ref_audio = self.clone_reference_audio if is_clone else None
                # Klon dili etiketinden iki harfli kodu çıkar (örn. "İngilizce (en)" → "en")
                _lang_match = re.search(r'\(([a-z]{2})\)', self.clone_lang_var.get())
                clone_lang = _lang_match.group(1) if _lang_match else "tr"

                lines = [scene.strip() for scene in re.split(r'\n\s*\n', text.strip()) if scene.strip()]

                # Her video sahnesi için ayrı seslendirme üret. (Sahne sayısı ile
                # video sayısının eşitliği start_processing'de zaten doğrulanır.)
                ext = "wav" if is_clone else "mp3"
                audio_to_use = []
                for i in range(len(self.video_files)):
                    if i < len(lines):
                        temp_audio = os.path.join(temp_dir, f"temp_voiceover_{i}.{ext}")
                        tts_generator.generate_audio(lines[i], temp_audio, voice=voice_code, rate=tts_rate, reference_audio=ref_audio, language=clone_lang)
                        audio_to_use.append(temp_audio)
                        temp_audios.append(temp_audio)
            else:
                self._set_status("Adım 1/2: Hazır ses dosyası ayarlanıyor...")
                audio_to_use = self.custom_audio_file

            self._set_status("Adım 2/2: Videolar birleştiriliyor. Bu işlem bilgisayar hızına göre vakit alabilir...")

            transition_duration = self.transition_var.get()
            transition_type = self.transition_type_var.get()
            bg_volume = self.bg_audio_volume.get() if self.bg_audio_enabled.get() else 0.0
            sync_to_audio = self.sync_to_audio_enabled.get()

            video_processor.process_video(
                self.video_files,
                audio_to_use,
                output_file,
                transition_duration=transition_duration,
                transition_type=transition_type,
                bg_audio_volume=bg_volume,
                sync_to_audio=sync_to_audio
            )

            if use_tts:
                for temp_audio in temp_audios:
                    if os.path.exists(temp_audio):
                        try:
                            os.remove(temp_audio)
                        except Exception as e:
                            print(f"Geçici dosya silinemedi {temp_audio}: {e}")

            self._set_status("İşlem Başarılı! Video kaydedildi.")
            self._show_message(messagebox.showinfo, "Başarılı", f"Video başarıyla oluşturuldu!\n\nKonum: {output_file}")

        except Exception as e:
            self._set_status("Hata oluştu!")
            print("\n--- BİR HATA OLUŞTU ---")
            traceback.print_exc(file=sys.stdout)
            self._show_message(messagebox.showerror, "Hata", f"İşlem sırasında bir hata oluştu:\n{str(e)}\n\nDetaylar için lütfen alttaki Log ekranını inceleyin.")

        finally:
            self._set_process_btn_state(tk.NORMAL)

if __name__ == "__main__":
    root = tk.Tk()
    app = VideoEditorApp(root)
    root.mainloop()
