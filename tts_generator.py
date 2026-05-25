import asyncio
import edge_tts
import os
import time

# Popüler Türkçe sesler:
# tr-TR-AhmetNeural (Erkek)
# tr-TR-EmelNeural (Kadın)

MAX_RETRIES = 3
RETRY_DELAY = 2  # saniye

_tts_model = None

def _get_xtts_model():
    global _tts_model
    if _tts_model is None:
        print("[TTS] XTTS v2 Modeli yükleniyor (Bu işlem ilk seferde biraz sürebilir)...")
        from TTS.api import TTS
        import torch
        os.environ["TTS_MODEL_LICENSE_ACCEPTED"] = "true"
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        print("[TTS] XTTS v2 Modeli başarıyla yüklendi!")
    return _tts_model

async def _generate_audio_async(text, output_file, voice="tr-TR-AhmetNeural", rate="+0%"):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_file)

def generate_audio(text, output_file, voice="tr-TR-AhmetNeural", rate="+0%", reference_audio=None):
    """
    Verilen metni ses dosyasına çevirir ve kaydeder.
    Eğer reference_audio verilmişse XTTS ile ses klonlama yapar.
    Aksi takdirde Edge-TTS kullanır.
    """
    if os.path.exists(output_file):
        try:
            os.remove(output_file)
        except Exception:
            pass

    if reference_audio:
        try:
            print(f"[TTS] Lokal ses klonlama başlatılıyor... Referans ses: {reference_audio}")
            model = _get_xtts_model()
            # XTTS Türkçe dil desteği için 'tr' kodu kullanılır.
            model.tts_to_file(text=text, speaker_wav=reference_audio, language="tr", file_path=output_file)
            print(f"[TTS] Ses klonlama ile başarıyla oluşturuldu.")
            return output_file
        except Exception as e:
            print(f"[TTS] Ses klonlama sırasında hata oluştu: {e}")
            raise e

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[TTS] Ses üretiliyor... Hız: {rate} (Deneme {attempt}/{MAX_RETRIES})")
            asyncio.run(_generate_audio_async(text, output_file, voice, rate=rate))
            print(f"[TTS] Ses başarıyla oluşturuldu.")
            return output_file
        except Exception as e:
            last_error = e
            err_str = str(e)
            print(f"[TTS] Deneme {attempt} başarısız: {err_str}")
            if attempt < MAX_RETRIES:
                print(f"[TTS] {RETRY_DELAY} saniye sonra tekrar deneniyor...")
                time.sleep(RETRY_DELAY)
    
    # Tüm denemeler başarısız olduysa
    raise RuntimeError(
        f"Ses üretimi {MAX_RETRIES} denemeden sonra başarısız oldu.\n\n"
        f"Son hata: {last_error}\n\n"
        f"Lütfen internet bağlantınızı kontrol edin veya VPN kullanmayı deneyin."
    )

if __name__ == "__main__":
    # Test
    generate_audio("Merhaba, bu bir test seslendirmesidir.", "test_ses.mp3")
    print("Test ses dosyası oluşturuldu: test_ses.mp3")
