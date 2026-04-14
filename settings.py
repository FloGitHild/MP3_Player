import json
import os

SETTINGS_FILE = os.path.expanduser("~/.music_player_settings.json")

DEFAULT_SETTINGS = {
    "fade_in_ms": 50,
    "fade_out_ms": 50,
    "last_folder": "",
    "restore_last_folder": True,
    "normalize_volume": False,
    "limiter": True
}


class Settings:
    def __init__(self):
        self.settings = self.load()
    
    def load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
                    settings = DEFAULT_SETTINGS.copy()
                    settings.update(data)
                    return settings
            except:
                pass
        return DEFAULT_SETTINGS.copy()
    
    def save(self):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(self.settings, f, indent=4)
    
    def get(self, key, default=None):
        return self.settings.get(key, default)
    
    def set(self, key, value):
        self.settings[key] = value
        self.save()
    
    @property
    def fade_in_ms(self):
        return self.settings.get("fade_in_ms", 50)
    
    @fade_in_ms.setter
    def fade_in_ms(self, value):
        self.settings["fade_in_ms"] = value
        self.save()
    
    @property
    def fade_out_ms(self):
        return self.settings.get("fade_out_ms", 50)
    
    @fade_out_ms.setter
    def fade_out_ms(self, value):
        self.settings["fade_out_ms"] = value
        self.save()
    
    @property
    def last_folder(self):
        return self.settings.get("last_folder", "")
    
    @last_folder.setter
    def last_folder(self, value):
        self.settings["last_folder"] = value
        self.save()
    
    @property
    def restore_last_folder(self):
        return self.settings.get("restore_last_folder", True)
    
    @restore_last_folder.setter
    def restore_last_folder(self, value):
        self.settings["restore_last_folder"] = value
        self.save()
    
    @property
    def normalize_volume(self):
        return self.settings.get("normalize_volume", False)
    
    @normalize_volume.setter
    def normalize_volume(self, value):
        self.settings["normalize_volume"] = value
        self.save()
    
    @property
    def limiter(self):
        return self.settings.get("limiter", True)
    
    @limiter.setter
    def limiter(self, value):
        self.settings["limiter"] = value
        self.save()
