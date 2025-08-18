import os
from config import PRESEED_PATH_1, PRESEED_PATH_2, PRESEED_ACTIVE_FILE

PRESEED_PATHS = [PRESEED_PATH_1, PRESEED_PATH_2]

def get_active_index():
    try:
        with open(PRESEED_ACTIVE_FILE, 'r', encoding='utf-8') as f:
            idx = int(f.read().strip())
            if idx in (1, 2):
                return idx
    except Exception:
        pass
    return 1

def set_active_index(idx: int):
    if idx not in (1, 2):
        raise ValueError('Invalid preseed index')
    os.makedirs(os.path.dirname(PRESEED_ACTIVE_FILE), exist_ok=True)
    with open(PRESEED_ACTIVE_FILE, 'w', encoding='utf-8') as f:
        f.write(str(idx))

def get_preseed_path(idx: int | None = None) -> str:
    if idx is None:
        idx = get_active_index()
    if idx not in (1, 2):
        raise ValueError('Invalid preseed index')
    return PRESEED_PATHS[idx - 1]
