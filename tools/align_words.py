"""Находит в готовых записях диктора начало и конец каждого слова и пишет words-uk.json / words-us.json.

Запуск (нужен faster-whisper из ~/stt, модель работает локально, платной озвучки не требует):
  flock -w 900 ~/.cache/stt.lock systemd-run --user --scope -q -p MemoryMax=2500M -- nice -n 10 \
    ~/stt/venv/bin/python -I tools/align_words.py uk

Слова берутся из текста карточки (поле en, делим по пробелам). Whisper распознаёт запись и даёт время слов;
распознанные слова сопоставляются с известным текстом, а пропущенные дорисовываются между соседями пропорционально длине.
Формат: {"колода": {"номер карточки": [["слово", начало_с, конец_с], ...]}}
"""
import difflib, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICE = sys.argv[1] if len(sys.argv) > 1 else "uk"
FOLDER = {"uk": "audio-uk", "us": "audio"}[VOICE]
os.environ.setdefault("HF_HOME", os.path.expanduser("~/stt/models"))
from faster_whisper import WhisperModel


def read_decks():
    src = open(os.path.join(ROOT, "cards.js"), encoding="utf-8").read()
    out = []
    for d in re.split(r'\n  \{ id: "', src)[1:]:
        deck = d.split('"')[0]
        dir_ = re.search(r'dir: "([^"]*)"', d).group(1)
        cards = [(int(i), en) for i, en in re.findall(r'\{ id: (\d+),.*?\ben: "((?:[^"\\]|\\.)*)"', d)]
        out.append((deck, dir_, cards))
    return out


norm = lambda w: re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))


def align(tokens, heard):
    """tokens — слова текста; heard — [(слово, нач, кон)] от whisper. Возвращает [нач, кон] для каждого токена."""
    a = [norm(t) for t in tokens]
    b = [norm(h[0]) for h in heard]
    res = [None] * len(tokens)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                res[i1 + k] = [heard[j1 + k][1], heard[j1 + k][2]]
    # слова без пары — по длине между соседями
    i = 0
    total_end = heard[-1][2] if heard else 0
    while i < len(res):
        if res[i] is not None:
            i += 1; continue
        j = i
        while j < len(res) and res[j] is None:
            j += 1
        t0 = res[i - 1][1] if i > 0 else (heard[0][1] if heard else 0)
        t1 = res[j][0] if j < len(res) else total_end
        t1 = max(t1, t0 + 0.05 * (j - i))
        w = [max(1, len(norm(tokens[k]))) for k in range(i, j)]
        acc = t0
        for k, wk in zip(range(i, j), w):
            nxt = acc + (t1 - t0) * wk / sum(w)
            res[k] = [acc, nxt]
            acc = nxt
        i = j
    # время не должно идти назад
    prev = 0
    for r in res:
        r[0] = max(r[0], prev) if r[0] < prev else r[0]
        r[1] = max(r[1], r[0] + 0.05)
        prev = r[1] - 0.0
    return res


def main():
    model = WhisperModel(os.environ.get("STT_MODEL", "large-v3-turbo"), device="cpu", compute_type="int8", cpu_threads=2,
                         download_root=os.path.expanduser("~/stt/models"))
    result, weak = {}, []
    for deck, dir_, cards in read_decks():
        result[deck] = {}
        for cid, en in cards:
            path = os.path.join(ROOT, FOLDER, dir_, f"{cid}.mp3")
            if not os.path.exists(path):
                continue
            tokens = en.replace("\\\"", '"').split()
            segs, _ = model.transcribe(path, language="en", beam_size=5, word_timestamps=True, vad_filter=False,
                                       condition_on_previous_text=False, initial_prompt=en)
            heard = [(w.word.strip(), w.start, w.end) for s in segs for w in (s.words or [])]
            if not heard:
                weak.append((deck, cid, "нет слов")); continue
            tm = align(tokens, heard)
            hit = len({norm(t) for t in tokens} & {norm(h[0]) for h in heard})
            if hit < 0.8 * len({norm(t) for t in tokens}):
                weak.append((deck, cid, f"совпало {hit}/{len(set(map(norm, tokens)))}"))
            result[deck][str(cid)] = [[t, round(a, 2), round(b, 2)] for t, (a, b) in zip(tokens, tm)]
            print(deck, cid, flush=True)
    json.dump(result, open(os.path.join(ROOT, f"words-{VOICE}.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("слабые места:", weak)


if __name__ == "__main__":
    main()
