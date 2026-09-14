"""Reference registry stores original paths only; audio is never copied."""
import ctypes, json, os, shutil, threading, uuid
from ctypes import wintypes
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse

_AUDIO_SUFFIXES={'.wav','.mp3','.flac','.m4a','.ogg','.aac','.opus'}
_PICKER_FLAGS=0x00000800|0x00001000|0x00080000|0x00000008|0x00000004
_REGISTRY_LOCK=threading.Lock()

def registry_path(data): return Path(data)/'reference-paths.json'

def _read_registry(data):
    registry=registry_path(data)
    return json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {}

def _write_registry(data,records):
    registry=registry_path(data)
    registry.parent.mkdir(parents=True,exist_ok=True)
    temp=registry.with_suffix('.tmp');temp.write_text(json.dumps(records,ensure_ascii=False),encoding='utf-8');temp.replace(registry)

def read_registry(data):
    """Return every registered reference; keys are opaque ids."""
    with _REGISTRY_LOCK: return _read_registry(data)

def register_reference_path(data,path,name=None):
    """Register an existing audio file by path; the audio itself is never copied."""
    source=Path(path)
    if not source.is_file() or source.suffix.lower() not in _AUDIO_SUFFIXES:
        raise HTTPException(400,'请选择有效音频文件。')
    item={'id':str(uuid.uuid4()),'path':str(source.resolve()),'name':name or source.name}
    with _REGISTRY_LOCK:
        saved=_read_registry(data);saved[item['id']]=item;_write_registry(data,saved)
    return item

class _OpenFileName(ctypes.Structure):
    _fields_=[
        ('lStructSize',wintypes.DWORD),('hwndOwner',wintypes.HWND),('hInstance',wintypes.HINSTANCE),
        ('lpstrFilter',wintypes.LPCWSTR),('lpstrCustomFilter',wintypes.LPWSTR),('nMaxCustFilter',wintypes.DWORD),
        ('nFilterIndex',wintypes.DWORD),('lpstrFile',wintypes.LPWSTR),('nMaxFile',wintypes.DWORD),
        ('lpstrFileTitle',wintypes.LPWSTR),('nMaxFileTitle',wintypes.DWORD),('lpstrInitialDir',wintypes.LPCWSTR),
        ('lpstrTitle',wintypes.LPCWSTR),('Flags',wintypes.DWORD),('nFileOffset',wintypes.WORD),
        ('nFileExtension',wintypes.WORD),('lpstrDefExt',wintypes.LPCWSTR),('lCustData',wintypes.LPARAM),
        ('lpfnHook',ctypes.c_void_p),('lpTemplateName',wintypes.LPCWSTR),
    ]

def _native_pick():
    """Open the Windows common dialog in-process, avoiding PowerShell startup."""
    if os.name!='nt': return False,''
    try:
        selected=ctypes.create_unicode_buffer(32768)
        filters='音频文件\0*.wav;*.mp3;*.flac;*.m4a;*.ogg;*.aac;*.opus\0所有文件\0*.*\0\0'
        dialog=_OpenFileName()
        dialog.lStructSize=ctypes.sizeof(_OpenFileName)
        dialog.lpstrFilter=filters
        dialog.nFilterIndex=1
        dialog.lpstrFile=selected
        dialog.nMaxFile=len(selected)
        dialog.lpstrTitle='选择参考音频（使用原文件）'
        dialog.Flags=_PICKER_FLAGS
        ok=ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(dialog))
        return True,selected.value if ok else ''
    except (AttributeError,OSError,TypeError):
        return False,''

def _tk_pick():
    """Fallback file dialog using the bundled Python Tk runtime."""
    if os.name!='nt': return False,''
    root=None
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
        path=filedialog.askopenfilename(title='选择参考音频（使用原文件）',filetypes=[('音频文件','*.wav *.mp3 *.flac *.m4a *.ogg *.aac *.opus'),('所有文件','*.*')])
        root.destroy()
        return True,path or ''
    except (ImportError,AttributeError,OSError,RuntimeError,TypeError):
        if root is not None:
            try: root.destroy()
            except Exception: pass
        return False,''

def install_reference_routes(app, data):
    picker_lock=threading.Lock()
    def resolve(key):
        item=read_registry(data).get(key)
        if not item or not Path(item['path']).is_file():
            raise HTTPException(404, '参考音频不存在或已移动，请重新选择。')
        return item
    @app.post('/api/v1/references/pick')
    def pick(body:dict|None=None):
        path=''
        with picker_lock:
            native, path=_native_pick()
            if not native:
                native, path=_tk_pick()
            if not native:
                raise HTTPException(503,'本地文件选择器无法打开，请确认当前桌面会话允许显示文件窗口。')
        if not path: return None
        source=Path(path)
        if not source.is_file() or source.suffix.lower() not in _AUDIO_SUFFIXES:
            raise HTTPException(400,'请选择有效音频文件。')
        return register_reference_path(data,source)
    @app.post('/api/v1/references/{key}/transcribe')
    def transcribe(key:str,body:dict|None=None):
        payload=body or {}
        preview=Path(data)/'transcription-previews'/uuid.uuid4().hex
        try:
            from .abc_processor import ABCReferenceProcessor
            from .cover import resolve_reference,transcribe_reference
            source=resolve_reference({'id':key,'range':payload.get('range'),'preserve':payload.get('preserve','melody'),'strength':payload.get('strength','balanced')},data)
            preview.mkdir(parents=True,exist_ok=True)
            progress=[]
            raw=transcribe_reference(source,preview,data,lambda:None,progress.append)
            processed=ABCReferenceProcessor().process(raw,source['strength'])
            return {'abc':processed,'source':source,'recommendedCot':'full' if source['preserve']=='full' else 'melody','progress':progress}
        except HTTPException:
            raise
        except (ValueError,OSError,RuntimeError,TypeError) as exc:
            raise HTTPException(422,str(exc)) from exc
        finally:
            shutil.rmtree(preview,ignore_errors=True)
    @app.get('/api/v1/references/{key}')
    def info(key:str): return resolve(key)
    @app.get('/api/v1/references/{key}/audio')
    def audio(key:str): return FileResponse(resolve(key)['path'])
