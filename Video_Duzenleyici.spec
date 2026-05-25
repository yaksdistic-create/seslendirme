# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata

datas = []
datas += copy_metadata('imageio')
datas += copy_metadata('imageio_ffmpeg')
datas += copy_metadata('moviepy')
datas += copy_metadata('edge-tts')

# Coqui TTS + PyTorch ve ağır bağımlılıklarını hariç tut (~2+ GB tasarruf)
heavy_excludes = [
    'TTS',
    'torch', 'torchvision', 'torchaudio',
    'tensorflow', 'keras',
    'scipy',
    'pandas',
    'matplotlib',
    'jupyter', 'notebook', 'ipykernel', 'ipywidgets',
    'sklearn', 'scikit-learn',
    'sympy',
    'transformers',
    'datasets',
    'tokenizers',
    'safetensors',
    'huggingface_hub',
    'trainer',
    'coqpit',
    'librosa',
    'soundfile',
    'gruut',
    'phonemizer',
    'umap',
    'numba',
    'llvmlite',
    'onnxruntime',
    'triton',
    'jinja2',
    'pytest',
    'sphinx',
    'docutils',
    'babel',
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    'wx',
    'cv2', 'opencv-python',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=heavy_excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Video_Duzenleyici',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
