"""Собирает из озвучки колод длинные аудио-тренировки с паузами внутри и пишет sessions.json.

Запуск из корня репозитория:  <python с PyAV и numpy> tools/build_sessions.py
Нужны файлы audio/ (американский голос) и audio-uk/ (британский). Результат: sessions/*.mp3 и sessions.json.

Виды тренировок:
  shadow — «Повтори за диктором»: фраза, затем тишина на её повтор вслух (1,3 длины фразы + 0,8 с, не меньше 1,5 с).
  drill  — «Дрил голосом»: команда, 5 с на действие и повтор фразы вслух, команда ещё раз для проверки, 1,5 с. Порядок: chain (как в колоде) и random (вразнобой, порядок фиксирован).

Готовые файлы нужны, потому что при выключенном экране браузер замедляет таймеры, и паузы, посчитанные в самом приложении, «плывут».
Приложение берёт расписание фраз (id карточки, начало, конец) из sessions.json: от него работают кнопки «предыдущая / следующая фраза» и показ текста.
"""
import json, os, random, re, sys
from fractions import Fraction
import av
import numpy as np

RATE = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "sessions")
os.makedirs(OUT, exist_ok=True)

DRILL_PAUSE = 5.0     # секунд на действие после команды
DRILL_GAP = 1.5       # пауза между командами
SHADOW_MIN = 1.5      # минимальная пауза для повтора
VOICES = {"uk": "audio-uk", "us": "audio"}
DRILL_DECKS = {"core", "cup"}   # дрил — только для колод с действиями


def read_decks():
    src = open(os.path.join(ROOT, "cards.js"), encoding="utf-8").read()
    decks = []
    for d in re.split(r'\n  \{ id: "', src)[1:]:
        deck_id = d.split('"')[0]
        name = re.search(r'name: "([^"]*)"', d).group(1)
        dir_ = re.search(r'dir: "([^"]*)"', d).group(1)
        ids = [int(x) for x in re.findall(r"\{ id: (\d+),", d)]
        decks.append({"id": deck_id, "name": name, "dir": dir_, "ids": ids})
    return decks


def pcm(path):
    """Читает mp3 в массив int16 mono 44,1 кГц."""
    c = av.open(path)
    rs = av.AudioResampler(format="s16p", layout="mono", rate=RATE)
    parts = []
    for fr in c.decode(audio=0):
        for out in rs.resample(fr):
            parts.append(out.to_ndarray()[0])
    for out in rs.resample(None):
        parts.append(out.to_ndarray()[0])
    c.close()
    return np.concatenate(parts).astype(np.int16)


class Writer:
    def __init__(self, path):
        self.out = av.open(path, "w", format="mp3")
        self.st = self.out.add_stream("libmp3lame", rate=RATE)
        self.st.bit_rate = 64000
        self.st.layout = "mono"
        self.n = 0   # записано сэмплов

    def write(self, samples):
        for i in range(0, len(samples), 4608):
            chunk = samples[i:i + 4608]
            fr = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16p", layout="mono")
            fr.sample_rate = RATE
            fr.pts = self.n
            fr.time_base = Fraction(1, RATE)
            for pkt in self.st.encode(fr):
                self.out.mux(pkt)
            self.n += len(chunk)

    def silence(self, sec):
        self.write(np.zeros(int(round(sec * RATE)), dtype=np.int16))

    def close(self):
        for pkt in self.st.encode(None):
            self.out.mux(pkt)
        self.out.close()

    @property
    def t(self):
        return self.n / RATE


def build(deck, kind, order, voice, cache):
    ids = deck["ids"][:]
    if order == "random":
        random.Random(7).shuffle(ids)
    name = f"{deck['id']}-{kind}{'-r' if order == 'random' else ''}-{voice}.mp3"
    w = Writer(os.path.join(OUT, name))
    items = []
    for i in ids:
        if i not in cache:
            cache[i] = pcm(os.path.join(ROOT, VOICES[voice], f"{deck['dir']}{i}.mp3"))
        a = cache[i]
        d = len(a) / RATE
        t0 = w.t
        w.write(a)
        if kind == "shadow":
            w.silence(max(SHADOW_MIN, 1.3 * d + 0.8))
        else:
            w.silence(DRILL_PAUSE)
            w.write(a)
            w.silence(DRILL_GAP)
        items.append([i, round(t0, 2), round(w.t, 2)])
    w.close()
    size = os.path.getsize(os.path.join(OUT, name))
    return {"id": name[:-4], "deck": deck["id"], "kind": kind, "order": order, "voice": voice,
            "file": f"sessions/{name}", "duration": round(items[-1][2]), "bytes": size, "items": items}


def main():
    sessions = []
    for deck in read_decks():
        for voice in VOICES:
            cache = {}
            kinds = [("shadow", "chain")]
            if deck["id"] in DRILL_DECKS:
                kinds += [("drill", "chain"), ("drill", "random")]
            for kind, order in kinds:
                s = build(deck, kind, order, voice, cache)
                sessions.append(s)
                print(f"{s['id']:<22} {s['duration']//60}:{s['duration']%60:02d}  {s['bytes']/1e6:.1f} МБ  фраз {len(s['items'])}", flush=True)
    json.dump({"sessions": sessions}, open(os.path.join(ROOT, "sessions.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("всего:", len(sessions), "файлов,", round(sum(s["bytes"] for s in sessions) / 1e6, 1), "МБ")


if __name__ == "__main__":
    main()
