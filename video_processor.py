import os
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips, ImageClip, CompositeAudioClip
import moviepy.video.fx.all as vfx
from proglog import ProgressBarLogger

class UILogger(ProgressBarLogger):
    def __init__(self):
        super().__init__()
        self.last_percent = -1
        self.current_action = "İşleniyor"

    def callback(self, **changes):
        for (message, value) in changes.items():
            if message == 'message':
                if "Writing audio" in value:
                    self.current_action = "Ses dışa aktarılıyor"
                    print("\n[Log] Ses dışa aktarma aşamasına geçildi...")
                    self.last_percent = -1
                elif "Writing video" in value:
                    self.current_action = "Video oluşturuluyor"
                    print("\n[Log] Video kareleri işleniyor...")
                    self.last_percent = -1

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar not in self.bars:
            return
        total = self.bars[bar].get('total', 0)
        if total > 0:
            percent = int((value / total) * 100)
            if percent != self.last_percent and percent % 5 == 0:
                print(f"> {self.current_action}: %{percent} tamamlandı.")
                self.last_percent = percent

def process_video(video_files, audio_input, output_file, transition_duration=1.0, transition_type="crossfade", bg_audio_volume=0.0, sync_to_audio=True):
    """
    Kısa videoları birleştirir, aralarına seçilen geçişi ekler ve
    ses dosyasını arka plan sesi olarak ayarlar.
    audio_input: Tek bir ses dosyası yolu (str) veya her video için ses yolları listesi (list)
    bg_audio_volume: Videolardaki orijinal arka plan sesinin seviyesi (0.0 = kapalı, 1.0 = tam ses)
    sync_to_audio: True ise video süresi seslendirmeye göre ayarlanır (seslendirme
        uzunsa son kare donar, kısaysa video kesilir). False ise videolar orijinal
        süresinde kalır ve seslendirme üzerine bindirilir (taşarsa kırpılır).
    """
    if not video_files:
        raise ValueError("Lütfen en az bir video dosyası seçin.")
        
    print("Videolar yükleniyor...")
    clips = []
    original_clips = []
    for f in video_files:
        clip = VideoFileClip(f)
        clips.append(clip)
        original_clips.append(clip)
    
    MIN_HEIGHT = 720  # Minimum hedef çözünürlük yüksekliği

    # 1. Geçiş: 720p altındaki klipleri upscale et
    print("--- Çözünürlük Kontrolü ---")
    for i in range(len(clips)):
        cw, ch = clips[i].size
        fname = os.path.basename(video_files[i])
        if ch < MIN_HEIGHT:
            scale = MIN_HEIGHT / ch
            new_w = int(cw * scale)
            new_h = MIN_HEIGHT
            print(f"⚠ Video {i+1} ({fname}): {cw}x{ch} düşük çözünürlük → {new_w}x{new_h}'e yükseltiliyor...")
            clips[i] = clips[i].resize((new_w, new_h))
        else:
            print(f"✓ Video {i+1} ({fname}): {cw}x{ch} — Değiştirilmedi.")

    # 2. Geçiş: Tüm kliplerin en yüksek çözünürlüğünü hedef al
    max_h = max(clip.size[1] for clip in clips)
    # En yüksek klible aynı en-boy oranını koruyarak hedef belirle
    ref_idx = next(i for i, c in enumerate(clips) if c.size[1] == max_h)
    target_w, target_h = clips[ref_idx].size
    target_fps = max(clip.fps or 30 for clip in clips)
    print(f"Hedef çözünürlük: {target_w}x{target_h}, FPS: {target_fps}")

    # 3. Geçiş: Tüm klipleri hedef boyuta getir
    for i in range(len(clips)):
        cw, ch = clips[i].size
        if cw != target_w or ch != target_h:
            clips[i] = clips[i].resize((target_w, target_h))
            print(f"Video {i+1} boyutu {cw}x{ch} → {target_w}x{target_h} olarak ayarlandı.")
        
    voiceover_clips = []
    single_voiceover = None
    # Crossfade etkinse klipler üst üste bineceğinden, sahne başına seslendirmede
    # konuşmanın sonunun kesilmesini önlemek için geçiş süresi kadar sessiz
    # dondurma kuyruğu eklenir.
    crossfade_active = (transition_duration > 0 and transition_type == "crossfade" and len(clips) > 1)

    if isinstance(audio_input, list):
        if len(audio_input) < len(clips):
            print("Uyarı: Ses dosyası sayısı video sayısından az, fazla videolar kullanılmayacak...")
            clips = clips[:len(audio_input)]

        if sync_to_audio:
            print("Her sahne için videoların süreleri ses dosyalarına göre ayarlanıyor...")
        else:
            print("Videolar orijinal süresinde tutuluyor; seslendirme üzerine bindiriliyor...")
        for i in range(len(clips)):
            if i < len(audio_input) and audio_input[i] and os.path.exists(audio_input[i]):
                voc = AudioFileClip(audio_input[i])
                voiceover_clips.append(voc)

                if sync_to_audio:
                    # Video süresini seslendirmeye eşitle (dondur / kırp).
                    # Konuşma süresi + (crossfade için) geçiş payı kadar sessiz kuyruk.
                    # Son klibe kuyruk eklenmez (sonrasında geçiş yok).
                    extra = transition_duration if (crossfade_active and i < len(clips) - 1) else 0.0
                    target_duration = voc.duration + extra

                    if clips[i].duration < target_duration:
                        last_frame = clips[i].get_frame(max(0, clips[i].duration - 0.05))
                        freeze_clip = ImageClip(last_frame).set_duration(target_duration - clips[i].duration)
                        freeze_clip.fps = clips[i].fps
                        clips[i] = concatenate_videoclips([clips[i], freeze_clip], method="compose")
                    else:
                        clips[i] = clips[i].subclip(0, target_duration)
                    audio_for_clip = voc
                else:
                    # Süre ayarlanmıyor: video orijinal kalır. Seslendirme klip
                    # süresini aşarsa kırpılır (videoyu uzatmayız), kısaysa kalan
                    # kısım sessiz kalır.
                    if voc.duration > clips[i].duration:
                        audio_for_clip = voc.subclip(0, clips[i].duration)
                    else:
                        audio_for_clip = voc

                # Orijinal arka plan sesini voiceover ile karıştır
                if bg_audio_volume > 0.0 and clips[i].audio is not None:
                    bg = clips[i].audio.volumex(bg_audio_volume)
                    mixed = CompositeAudioClip([bg, audio_for_clip])
                    clips[i] = clips[i].set_audio(mixed)
                else:
                    clips[i] = clips[i].set_audio(audio_for_clip)

    elif isinstance(audio_input, str) and os.path.exists(audio_input):
        single_voiceover = AudioFileClip(audio_input)
        if sync_to_audio:
            print("Tek parça ses dosyası bulundu. Videolar hedef ses süresine göre ayarlanıyor...")
            target_total_duration = single_voiceover.duration

            N = len(clips)
            if transition_duration > 0 and N > 1 and transition_type == "crossfade":
                target_clip_duration = (target_total_duration + (N - 1) * transition_duration) / N
            else:
                target_clip_duration = target_total_duration / N

            for i in range(N):
                if clips[i].duration < target_clip_duration:
                    last_frame = clips[i].get_frame(max(0, clips[i].duration - 0.05))
                    freeze_clip = ImageClip(last_frame).set_duration(target_clip_duration - clips[i].duration)
                    freeze_clip.fps = clips[i].fps
                    clips[i] = concatenate_videoclips([clips[i], freeze_clip], method="compose")
                else:
                    clips[i] = clips[i].subclip(0, target_clip_duration)
        else:
            print("Tek parça ses dosyası bulundu. Videolar orijinal süresinde tutuluyor; ses üzerine bindiriliyor...")

    print(f"Videolar birleştiriliyor. Geçiş Türü: {transition_type}...")
    
    if transition_duration > 0 and len(clips) > 1:
        if transition_type == "crossfade":
            final_clips = [clips[0]]
            for clip in clips[1:]:
                final_clips.append(clip.crossfadein(transition_duration))
            final_video = concatenate_videoclips(final_clips, padding=-transition_duration, method="compose")
            
        elif transition_type == "fade":
            final_clips = []
            for i, clip in enumerate(clips):
                c = clip
                if i > 0:
                    c = c.fx(vfx.fadein, transition_duration)
                if i < len(clips) - 1:
                    c = c.fx(vfx.fadeout, transition_duration)
                final_clips.append(c)
            final_video = concatenate_videoclips(final_clips, method="compose")
            
        else: # "none"
            final_video = concatenate_videoclips(clips, method="compose")
    else:
        final_video = concatenate_videoclips(clips, method="compose")
        
    if single_voiceover is not None:
        print("Tek parça ses dosyası tüm videoya ekleniyor...")
        # single_voiceover yukarıda zaten açıldı; tekrar açmıyoruz (handle sızıntısını önler).
        # Süre eşitleme kapalıysa ve ses videodan uzunsa, videoyu uzatmamak için
        # sesi video süresine kırp.
        voiceover_for_final = single_voiceover
        if not sync_to_audio and single_voiceover.duration > final_video.duration:
            voiceover_for_final = single_voiceover.subclip(0, final_video.duration)
        # Orijinal arka plan sesini tek parça ses ile karıştır
        if bg_audio_volume > 0.0 and final_video.audio is not None:
            bg = final_video.audio.volumex(bg_audio_volume)
            mixed = CompositeAudioClip([bg, voiceover_for_final])
            final_video = final_video.set_audio(mixed)
        else:
            final_video = final_video.set_audio(voiceover_for_final)

    # MoviePy crossfade süre düzeltmesi: yalnızca süre eşitleme açıkken videoyu
    # ses süresine sabitle. Kapalıyken videolar orijinal süresinde kalmalı.
    if sync_to_audio and final_video.audio:
        final_video = final_video.set_duration(final_video.audio.duration)

    print("Çıktı video oluşturuluyor (Bu işlem biraz zaman alabilir)...")
    
    logger = UILogger()
    # Geçici ses dosyasını çıktı videosunun bulunduğu klasöre kaydet.
    # dirname boş dönerse (yol klasör içermiyorsa) çalışma dizinine düş; aksi
    # halde os.chdir("") FileNotFoundError fırlatır.
    output_dir = os.path.dirname(output_file) or os.getcwd()
    temp_audio_path = os.path.join(output_dir, f"temp_audio_{os.path.basename(output_file)}.m4a")
    
    # MoviePy geçici dosyalarının masaüstüne gitmemesi için çalışma dizinini çıktı klasörüne al
    original_cwd = os.getcwd()
    os.chdir(output_dir)
    try:
        final_video.write_videofile(
            output_file, 
            codec="libx264", 
            audio_codec="aac", 
            fps=target_fps,
            threads=4,
            preset="medium",
            bitrate="8000k",
            temp_audiofile=temp_audio_path,
            logger=logger
        )
    finally:
        os.chdir(original_cwd)  # Her durumda eski dizine geri dön
    
    print("İşlem tamamlandı, hafıza temizleniyor...")
    try:
        final_video.close()
    except:
        pass
        
    for clip in clips:
        try:
            clip.close()
        except:
            pass
            
    for clip in original_clips:
        try:
            clip.close()
        except:
            pass
            
    for voc in voiceover_clips:
        try:
            voc.close()
        except:
            pass
            
    if single_voiceover:
        try:
            single_voiceover.close()
        except:
            pass
    
    return output_file
