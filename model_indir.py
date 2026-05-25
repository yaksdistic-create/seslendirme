import torch
from TTS.api import TTS

print("PyTorch CUDA Aktif mi?:", torch.cuda.is_available())
print("XTTS Modeli İndiriliyor/Yükleniyor...")

try:
    # Bu işlem modeli indirecektir ve ilerleme durumunu konsolda gösterecektir.
    import os
    # Coqui lisans (CPML) onayini otomatik kabul et (konsoldaki [y/n] sorusunu atlar)
    os.environ["COQUI_TOS_AGREED"] = "1"
    # PyTorch 2.6+ weights_only=True varsayilanini gecersiz kil (guvenilir model)
    _orig_torch_load = torch.load
    def _safe_torch_load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return _orig_torch_load(*args, **kwargs)
    torch.load = _safe_torch_load
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    print("\n[OK] Model başarıyla indirildi ve yüklendi!")
except Exception as e:
    print(f"\n[HATA] Bir hata oluştu: {e}")
