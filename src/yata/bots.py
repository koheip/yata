"""ボット（ヤタの分身）の見た目と入力チェック。

ボットごとに名前、任せる仕事、カラスの見た目（体の色 × 小物）を持つ。
既定のボット「ヤタ」は消せない。
"""

from __future__ import annotations

import random
from collections.abc import Iterable

DEFAULT_BOT_ID = "yata"
DEFAULT_BOT_NAME = "ヤタ"
DEFAULT_BOT_JOB = "なんでも頼める相棒"

BOT_COLORS: dict[str, str] = {
    "purple": "江戸紫",
    "blue": "藍",
    "green": "松葉",
    "orange": "柿",
    "pink": "牡丹",
    "gray": "鈍",
}

BOT_ACCESSORIES: dict[str, str] = {
    "none": "なし",
    "phones": "ヘッドホン",
    "glasses": "メガネ",
    "beret": "ベレー帽",
    "bow": "蝶ネクタイ",
    "scarf": "マフラー",
    "leaf": "葉っぱ",
}

MAX_NAME = 20
MAX_JOB = 200


class BotError(ValueError):
    """利用者に見せる日本語のメッセージを持つ入力エラー。"""


def clean_name(value: str) -> str:
    name = " ".join(value.split())
    if not name:
        raise BotError("ボットの名前を入れてください。")
    if len(name) > MAX_NAME:
        raise BotError(f"ボットの名前は{MAX_NAME}文字までにしてください。")
    return name


def clean_job(value: str | None) -> str:
    job = " ".join((value or "").split())
    if len(job) > MAX_JOB:
        raise BotError(f"任せる仕事は{MAX_JOB}文字までにしてください。")
    return job


def check_look(color: str, accessory: str) -> None:
    if color not in BOT_COLORS:
        raise BotError("体の色が正しくありません。")
    if accessory not in BOT_ACCESSORIES:
        raise BotError("小物が正しくありません。")


def pick_look(used: Iterable[tuple[str, str]], rng: random.Random | None = None) -> tuple[str, str]:
    """まだ誰も使っていない「色 × 小物」を選ぶ。全部使っていたら重なってもよい。"""
    taken = set(used)
    free = [(c, a) for c in BOT_COLORS for a in BOT_ACCESSORIES if (c, a) not in taken]
    chooser = rng or random
    if not free:
        return chooser.choice(list(BOT_COLORS)), chooser.choice(list(BOT_ACCESSORIES))
    return chooser.choice(free)
