import torch
from TTS.api import TTS

print("PyTorch CUDA Aktif mi?:", torch.cuda.is_available())
print("XTTS Modeli İndiriliyor/Yükleniyor...")

try:
    # Bu işlem modeli indirecektir ve ilerleme durumunu konsolda gösterecektir.
    import os
    os.environ["TTS_MODEL_LICENSE_ACCEPTED"] = "true"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    print("\n[OK] Model başarıyla indirildi ve yüklendi!")
except Exception as e:
    print(f"\n❌ Bir hata oluştu: {e}")
