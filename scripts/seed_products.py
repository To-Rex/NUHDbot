"""Test catalogue: real drive models in every catalogue direction (Desktop, Surveillance, NAS, Enterprise, Data Center,
Gaming) at approximate wholesale prices, for trying the shop out end to end.

    uv run python -m scripts.seed_products            # add what is missing (idempotent)
    uv run python -m scripts.seed_products --remove   # take the test products out again

Products are built the way the admin form builds them: brand linked, series from the dictionary (a missing series is
added with its direction colour), colour from the series, warranties by condition, texts in every language, a price
history ("created", plus a recent cut on a few so Discounts has content), an audit entry and the model dictionary entry
that feeds the autocomplete. No photos: cards show the drive placeholder until staff upload real ones.
The ids of the products added are kept in the `test_catalog_ids` setting; --remove deletes only those (a product
already on an order or an auction is hidden instead), so products staff enter by hand are never touched.
"""
import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import exists, func, select

from app.admin.common import snapshot
from app.admin.products import PRODUCT_FIELDS, WARRANTY_DEFAULTS
from app.config import settings
from app.db import session_scope
from app.enums import Condition, FormFactor, Interface, Purpose, TestStatus
from app.models import Auction, BrandModel, OrderItem, PriceHistory, Product, Series
from app.services import audit, model_dict
from app.services import brands as brand_service
from app.services import series as series_service
from app.services.settings_service import get_setting, set_setting
from scripts.translit_uz import translit

IDS_KEY = "test_catalog_ids"
WD, SG, TS, HG = "Western Digital", "Seagate", "Toshiba", "HGST / Ultrastar"
SHORT = {WD: "WD", SG: "Seagate", TS: "Toshiba", HG: "HGST"}
NEW, USED, REFRESH = Condition.NEW, Condition.USED, Condition.REFRESH

# Per series: factory warranty in months when new, and the specs shown on the product page.
SERIES_INFO: dict[tuple[str, str], tuple[int, dict]] = {
    (WD, "Blue"): (24, {}), (SG, "BarraCuda"): (24, {}), (TS, "P300"): (24, {}),
    (WD, "Purple"): (36, {"Recording": "CMR", "Workload": "180 TB/yr"}), (WD, "Purple Pro"): (60, {"Recording": "CMR", "Workload": "550 TB/yr"}),
    (SG, "SkyHawk"): (36, {"Recording": "CMR", "Workload": "180 TB/yr"}), (SG, "SkyHawk AI"): (60, {"Recording": "CMR", "Workload": "550 TB/yr"}),
    (TS, "S300"): (36, {"Workload": "180 TB/yr"}), (TS, "S300 Pro"): (36, {"Workload": "300 TB/yr"}),
    (WD, "Red Plus"): (36, {"Recording": "CMR", "Workload": "180 TB/yr"}), (WD, "Red Pro"): (60, {"Recording": "CMR", "Workload": "300 TB/yr"}),
    (SG, "IronWolf"): (36, {"Recording": "CMR", "Workload": "180 TB/yr"}), (SG, "IronWolf Pro"): (60, {"Recording": "CMR", "Workload": "550 TB/yr"}),
    (TS, "N300"): (36, {"Recording": "CMR", "Workload": "180 TB/yr"}),
    (WD, "Gold"): (60, {"Recording": "CMR", "Workload": "550 TB/yr"}), (SG, "Exos"): (60, {"Recording": "CMR", "Workload": "550 TB/yr"}),
    (TS, "MG"): (60, {"Recording": "CMR", "Workload": "550 TB/yr"}), (HG, "Ultrastar"): (60, {"Recording": "CMR", "Workload": "550 TB/yr"}),
    (SG, "Exos X16"): (60, {"Recording": "CMR", "Workload": "550 TB/yr", "Fill": "Helium"}),
    (SG, "Exos X18"): (60, {"Recording": "CMR", "Workload": "550 TB/yr", "Fill": "Helium"}),
    (SG, "Exos X20"): (60, {"Recording": "CMR", "Workload": "550 TB/yr", "Fill": "Helium"}),
    (SG, "Exos X24"): (60, {"Recording": "CMR", "Workload": "550 TB/yr", "Fill": "Helium"}),
    (HG, "Ultrastar DC"): (60, {"Recording": "CMR", "Workload": "550 TB/yr", "Fill": "Helium"}),
    (WD, "White"): (0, {"Recording": "CMR", "Fill": "Helium"}),
    (WD, "Black"): (60, {}), (SG, "FireCuda"): (60, {}), (TS, "X300"): (24, {}),
}

# direction colour → rows: (brand, model, series, GB, rpm, cache MB, condition, price USD, stock, options)
# options: ff="2.5", iface="SAS", label=<model on the label> (Refresh), hours/health (used), min/box/full_box,
#          was=<price before a recent cut>, test="tested"/"testing" (new drives are sealed = untested), flash=<SSHD cache>
CATALOG: dict[str, list[tuple]] = {
    "blue": [
        (WD, "WD10EZEX", "Blue", 1000, 7200, 64, NEW, 38, 240, {}),
        (WD, "WD20EZBX", "Blue", 2000, 7200, 256, NEW, 56, 160, {}),
        (WD, "WD40EZAX", "Blue", 4000, 5400, 256, NEW, 82, 90, {"was": 89}),
        (WD, "WD60EZAX", "Blue", 6000, 5400, 256, NEW, 118, 40, {}),
        (WD, "WD10SPZX", "Blue", 1000, 5400, 128, NEW, 45, 120, {"ff": "2.5"}),
        (WD, "WD20EZAZ", "Blue", 2000, 5400, 256, USED, 24, 85, {"hours": 21340, "health": "96%"}),
        (SG, "ST1000DM010", "BarraCuda", 1000, 7200, 64, NEW, 36, 300, {"min": 20, "full_box": True}),
        (SG, "ST2000DM008", "BarraCuda", 2000, 7200, 256, NEW, 54, 200, {}),
        (SG, "ST4000DM004", "BarraCuda", 4000, 5400, 256, NEW, 79, 120, {}),
        (SG, "ST8000DM004", "BarraCuda", 8000, 5400, 256, NEW, 139, 4, {}),
        (SG, "ST2000LM015", "BarraCuda", 2000, 5400, 128, NEW, 62, 60, {"ff": "2.5"}),
        (TS, "HDWD110UZSVA", "P300", 1000, 7200, 64, NEW, 35, 150, {}),
        (TS, "HDWD240UZSVA", "P300", 4000, 5400, 128, NEW, 78, 70, {}),
        (TS, "DT01ACA200", "P300", 2000, 7200, 64, REFRESH, 33, 140, {"label": "HDWD120UZSVA"}),
    ],
    "purple": [
        (WD, "WD11PURZ", "Purple", 1000, 5400, 64, NEW, 42, 180, {}),
        (WD, "WD23PURZ", "Purple", 2000, 5400, 64, NEW, 58, 220, {}),
        (WD, "WD43PURZ", "Purple", 4000, 5400, 256, NEW, 88, 160, {"test": "tested"}),
        (WD, "WD64PURZ", "Purple", 6000, 5400, 256, NEW, 128, 60, {}),
        (WD, "WD84PURZ", "Purple", 8000, 5640, 256, NEW, 172, 35, {"was": 185}),
        (WD, "WD121PURP", "Purple Pro", 12000, 7200, 256, NEW, 259, 12, {}),
        (WD, "WD40PURX", "Purple", 4000, 5400, 64, REFRESH, 49, 90, {"label": "WD40PURZ"}),
        (SG, "ST2000VX015", "SkyHawk", 2000, 5900, 64, NEW, 55, 190, {}),
        (SG, "ST4000VX016", "SkyHawk", 4000, 5400, 256, NEW, 84, 150, {}),
        (SG, "ST6000VX009", "SkyHawk", 6000, 5400, 256, NEW, 122, 50, {}),
        (SG, "ST8000VE001", "SkyHawk AI", 8000, 7200, 256, NEW, 165, 30, {"test": "testing"}),
        (SG, "ST12000VE001", "SkyHawk AI", 12000, 7200, 256, NEW, 245, 0, {}),
        (SG, "ST4000VX007", "SkyHawk", 4000, 5900, 64, USED, 44, 75, {"hours": 18420, "health": "94%"}),
        (TS, "HDWT140UZSVA", "S300", 4000, 5400, 128, NEW, 80, 100, {}),
        (TS, "HDWT380UZSVA", "S300 Pro", 8000, 7200, 256, NEW, 160, 25, {}),
    ],
    "red": [
        (WD, "WD20EFZX", "Red Plus", 2000, 5400, 128, NEW, 72, 110, {}),
        (WD, "WD40EFZX", "Red Plus", 4000, 5400, 128, NEW, 99, 140, {"was": 108}),
        (WD, "WD60EFZX", "Red Plus", 6000, 5640, 128, NEW, 139, 60, {}),
        (WD, "WD80EFZZ", "Red Plus", 8000, 5640, 128, NEW, 179, 45, {}),
        (WD, "WD4003FFBX", "Red Pro", 4000, 7200, 256, NEW, 139, 30, {}),
        (WD, "WD161KFGX", "Red Pro", 16000, 7200, 512, NEW, 329, 14, {}),
        (WD, "WD40EFRX", "Red Plus", 4000, 5400, 64, REFRESH, 62, 80, {"label": "WD40EFZX"}),
        (SG, "ST2000VN004", "IronWolf", 2000, 5900, 64, NEW, 69, 120, {}),
        (SG, "ST4000VN006", "IronWolf", 4000, 5400, 256, NEW, 95, 130, {}),
        (SG, "ST8000VN004", "IronWolf", 8000, 7200, 256, NEW, 175, 40, {}),
        (SG, "ST12000NT001", "IronWolf Pro", 12000, 7200, 256, NEW, 259, 18, {}),
        (SG, "ST16000NT001", "IronWolf Pro", 16000, 7200, 256, NEW, 309, 3, {}),
        (SG, "ST4000VN008", "IronWolf", 4000, 5900, 64, USED, 52, 65, {"hours": 24110, "health": "95%"}),
        (TS, "HDWG440UZSVA", "N300", 4000, 7200, 256, NEW, 96, 70, {}),
        (TS, "HDWG480UZSVA", "N300", 8000, 7200, 256, NEW, 172, 35, {}),
    ],
    "gold": [
        (WD, "WD1005FBYZ", "Gold", 1000, 7200, 128, NEW, 79, 60, {}),
        (WD, "WD4003FRYZ", "Gold", 4000, 7200, 256, NEW, 149, 40, {}),
        (WD, "WD8004FRYZ", "Gold", 8000, 7200, 256, NEW, 219, 25, {"was": 235}),
        (WD, "WD102KRYZ", "Gold", 10000, 7200, 256, NEW, 249, 12, {}),
        (SG, "ST4000NM000A", "Exos", 4000, 7200, 256, NEW, 109, 80, {}),
        (SG, "ST8000NM000A", "Exos", 8000, 7200, 256, NEW, 169, 50, {}),
        (SG, "ST4000NM0025", "Exos", 4000, 7200, 128, USED, 42, 120, {"iface": "SAS", "hours": 31560, "health": "93%"}),
        (TS, "MG06ACA800E", "MG", 8000, 7200, 256, NEW, 165, 30, {}),
        (TS, "MG08ADA800E", "MG", 8000, 7200, 256, NEW, 172, 20, {"test": "tested"}),
        (TS, "MG04ACA400E", "MG", 4000, 7200, 128, USED, 45, 150, {"hours": 28940, "health": "95%"}),
        (TS, "MG04ACA400N", "MG", 4000, 7200, 128, REFRESH, 49, 100, {"label": "MG04ACA400E"}),
        (HG, "HUS726T4TALA6L4", "Ultrastar", 4000, 7200, 256, NEW, 119, 45, {}),
        (HG, "HUS726060ALE610", "Ultrastar", 6000, 7200, 128, USED, 55, 90, {"hours": 33210, "health": "92%"}),
        (HG, "HUS724040ALE640", "Ultrastar", 4000, 7200, 64, USED, 38, 160, {"hours": 41020, "health": "90%"}),
        (HG, "HUS726T6TAL5204", "Ultrastar", 6000, 7200, 256, USED, 58, 70, {"iface": "SAS", "hours": 26480, "health": "96%"}),
    ],
    "silver": [
        (SG, "ST16000NM001G", "Exos X16", 16000, 7200, 256, NEW, 289, 30, {}),
        (SG, "ST18000NM000J", "Exos X18", 18000, 7200, 256, NEW, 319, 24, {"was": 339}),
        (SG, "ST18000NM004J", "Exos X18", 18000, 7200, 256, USED, 189, 40, {"iface": "SAS", "hours": 19830, "health": "97%"}),
        (SG, "ST20000NM007D", "Exos X20", 20000, 7200, 256, NEW, 349, 16, {}),
        (SG, "ST24000NM002H", "Exos X24", 24000, 7200, 512, NEW, 429, 8, {}),
        (HG, "HUH721212ALE600", "Ultrastar DC", 12000, 7200, 256, USED, 109, 110, {"hours": 27650, "health": "95%"}),
        (HG, "WUH721414ALE6L4", "Ultrastar DC", 14000, 7200, 512, NEW, 249, 26, {}),
        (HG, "WUH721816ALE6L4", "Ultrastar DC", 16000, 7200, 512, NEW, 279, 20, {}),
        (HG, "WUH721818AL5204", "Ultrastar DC", 18000, 7200, 512, USED, 199, 32, {"iface": "SAS", "hours": 15620, "health": "98%"}),
        (HG, "WUH722020BLE6L4", "Ultrastar DC", 20000, 7200, 512, NEW, 339, 10, {}),
        (WD, "WD120EMFZ", "White", 12000, 5400, 256, NEW, 199, 40, {}),
        (WD, "WD140EDGZ", "White", 14000, 5400, 512, NEW, 219, 35, {}),
        (WD, "WD180EDGZ", "White", 18000, 5400, 512, NEW, 289, 5, {}),
    ],
    "black": [
        (WD, "WD1003FZEX", "Black", 1000, 7200, 64, NEW, 69, 80, {}),
        (WD, "WD2003FZEX", "Black", 2000, 7200, 64, NEW, 95, 60, {}),
        (WD, "WD4005FZBX", "Black", 4000, 7200, 256, NEW, 149, 40, {"was": 159}),
        (WD, "WD6003FZBX", "Black", 6000, 7200, 256, NEW, 189, 25, {}),
        (WD, "WD8001FZBX", "Black", 8000, 7200, 256, NEW, 229, 15, {}),
        (WD, "WD101FZBX", "Black", 10000, 7200, 256, NEW, 269, 10, {}),
        (WD, "WD10SPSX", "Black", 1000, 7200, 64, NEW, 59, 70, {"ff": "2.5"}),
        (WD, "WD2003FZEX", "Black", 2000, 7200, 64, USED, 39, 45, {"hours": 16240, "health": "97%"}),
        (SG, "ST2000DX002", "FireCuda", 2000, 7200, 64, NEW, 85, 50, {"flash": "8 GB"}),
        (SG, "ST1000LX015", "FireCuda", 1000, 5400, 128, NEW, 62, 60, {"ff": "2.5", "flash": "8 GB"}),
        (SG, "ST2000LX001", "FireCuda", 2000, 5400, 128, NEW, 89, 40, {"ff": "2.5", "flash": "8 GB"}),
        (TS, "HDWE140UZSVA", "X300", 4000, 7200, 128, NEW, 112, 45, {}),
        (TS, "HDWE160UZSVA", "X300", 6000, 7200, 128, NEW, 149, 30, {}),
        (TS, "HDWR180UZSVA", "X300", 8000, 7200, 256, NEW, 189, 20, {}),
    ],
}

PURPOSES = {"blue": [Purpose.PC], "purple": [Purpose.CCTV], "red": [Purpose.NAS], "gold": [Purpose.SERVER],
            "silver": [Purpose.SERVER, Purpose.STORAGE], "black": [Purpose.PC]}

# Texts: uz (Cyrillic), ru, en, zh; uzl is transliterated from uz.
ABOUT = {
    "blue": {"uz": "{name} — уй ва офис компьютерлари учун {cap} диск: ҳужжатлар, фото, дастурлар ва ўйинлар. Тинч ишлайди ва кам қизийди.",
             "ru": "{name} — диск {cap} для домашних и офисных компьютеров: документы, фото, программы и игры. Работает тихо и почти не греется.",
             "en": "{name} — a {cap} drive for home and office PCs: documents, photos, software and games. Runs quiet and cool.",
             "zh": "{name} — {cap} 台式机硬盘，适用于家用和办公电脑：文档、照片、软件和游戏。运行安静、发热低。"},
    "purple": {"uz": "{name} — DVR ва NVR тизимларида 24/7 видео ёзиш учун {cap} диск: кўп камера оқими ва узлуксиз ёзишга мослашган.",
               "ru": "{name} — диск {cap} для круглосуточной записи видео в DVR и NVR: рассчитан на много потоков с камер и постоянную запись.",
               "en": "{name} — a {cap} drive for 24/7 video recording in DVR and NVR systems: tuned for many camera streams and constant writes.",
               "zh": "{name} — {cap} 监控硬盘，适用于 DVR/NVR 7×24 小时录像：针对多路摄像头和持续写入优化。"},
    "red": {"uz": "{name} — 24/7 ишлайдиган NAS ва кичик офис серверлари учун {cap} диск: кўп дискли RAID массивлар, тебранишдан ҳимоя.",
            "ru": "{name} — диск {cap} для NAS и небольших офисных серверов, работающих 24/7 в многодисковых RAID-массивах, с защитой от вибрации.",
            "en": "{name} — a {cap} drive for NAS and small office servers running 24/7 in multi-bay RAID arrays, with vibration protection.",
            "zh": "{name} — {cap} NAS 硬盘，适用于 7×24 小时运行的 NAS 和小型办公服务器，多盘位 RAID，具备防振保护。"},
    "gold": {"uz": "{name} — сервер ва иш станциялари учун корпоратив синфдаги {cap} диск: юқори иш юки ва барқарор 24/7 ишлаш.",
             "ru": "{name} — диск {cap} корпоративного класса для серверов и рабочих станций: высокая нагрузка и стабильная работа 24/7.",
             "en": "{name} — an enterprise-class {cap} drive for servers and workstations: high workload rating and steady 24/7 operation.",
             "zh": "{name} — {cap} 企业级硬盘，适用于服务器和工作站：高工作负载，7×24 小时稳定运行。"},
    "silver": {"uz": "{name} — маълумот марказлари, сақлаш тизимлари ва захира нусхалар учун катта ҳажмли {cap} диск: ҳар бир ўринга максимал терабайт.",
               "ru": "{name} — диск большой ёмкости {cap} для дата-центров, систем хранения и резервного копирования: максимум терабайт на отсек.",
               "en": "{name} — a high-capacity {cap} drive for data centres, storage arrays and backups: the most terabytes per bay.",
               "zh": "{name} — {cap} 大容量数据中心硬盘，适用于数据中心、存储阵列和备份系统：每个盘位容量最大化。"},
    "black": {"uz": "{name} — ўйин компьютерлари учун юқори унумли {cap} диск: катта ўйин кутубхоналари тез юкланади.",
              "ru": "{name} — производительный диск {cap} для игровых ПК: быстрая загрузка больших игровых библиотек.",
              "en": "{name} — a high-performance {cap} drive for gaming PCs: large game libraries load fast.",
              "zh": "{name} — {cap} 高性能游戏硬盘，适用于游戏电脑：大型游戏库快速加载。"},
}
SMALL = {"uz": "2.5″ ўлчам: ноутбук, мини-ПК ва ташқи қутиларга мос.", "ru": "Формат 2.5″: подходит для ноутбуков, мини-ПК и внешних боксов.",
         "en": "2.5″ size: fits laptops, mini PCs and external enclosures.", "zh": "2.5″ 尺寸：适用于笔记本、迷你主机和移动硬盘盒。"}
HYBRID = {"uz": "Гибрид (SSHD): {flash} флеш-кэш кўп ишлатиладиган файлларни тезлаштиради.", "ru": "Гибридный (SSHD): {flash} флеш-кэша ускоряют часто используемые файлы.",
          "en": "Hybrid (SSHD): a {flash} flash cache speeds up frequently used files.", "zh": "混合硬盘 (SSHD)：{flash} 闪存缓存可加速常用文件。"}
COMPAT = {
    ("SATA", "3.5"): {"uz": "SATA III (6 Gb/s) порт, стандарт 3.5″ ўрин: компьютер, DVR/NVR, NAS ёки сервер. SATA II портда ҳам ишлайди.",
                      "ru": "Порт SATA III (6 Гбит/с), стандартный отсек 3.5″: ПК, DVR/NVR, NAS или сервер. Работает и на SATA II.",
                      "en": "SATA III (6 Gb/s) port, standard 3.5″ bay: PC, DVR/NVR, NAS or server. Also works on SATA II.",
                      "zh": "SATA III (6 Gb/s) 接口，标准 3.5″ 盘位：电脑、DVR/NVR、NAS 或服务器。兼容 SATA II。"},
    ("SATA", "2.5"): {"uz": "SATA III (6 Gb/s) порт, 2.5″ ўрин, қалинлиги 7 мм: ноутбук, мини-ПК, ташқи қути.",
                      "ru": "Порт SATA III (6 Гбит/с), отсек 2.5″, толщина 7 мм: ноутбук, мини-ПК, внешний бокс.",
                      "en": "SATA III (6 Gb/s) port, 2.5″ bay, 7 mm thick: laptop, mini PC, external enclosure.",
                      "zh": "SATA III (6 Gb/s) 接口，2.5″ 盘位，厚度 7 mm：笔记本、迷你主机、移动硬盘盒。"},
    ("SAS", "3.5"): {"uz": "SAS 12 Gb/s: SAS контроллер ёки backplane (HBA/RAID) керак, оддий SATA портда ишламайди. 3.5″ сервер ўрни.",
                     "ru": "SAS 12 Гбит/с: нужен SAS-контроллер или бэкплейн (HBA/RAID), к обычному SATA-порту не подключается. Серверный отсек 3.5″.",
                     "en": "SAS 12 Gb/s: needs a SAS controller or backplane (HBA/RAID); does not work on an ordinary SATA port. 3.5″ server bay.",
                     "zh": "SAS 12 Gb/s：需要 SAS 控制器或背板 (HBA/RAID)，普通 SATA 接口无法使用。3.5″ 服务器盘位。"},
}
TESTED = {"uz": "SMART: қайта тайинланган ва кутилаётган секторлар 0. Тўлиқ сирт текшируви ўтди.", "ru": "SMART: 0 переназначенных и 0 ожидающих секторов. Полная проверка поверхности пройдена.",
          "en": "SMART: 0 reallocated and 0 pending sectors. Full surface scan passed.", "zh": "SMART：重映射扇区 0，待映射扇区 0。全盘表面扫描通过。"}
HOURS = {"uz": "Ишлаган вақти: {hours} соат.", "ru": "Наработка: {hours} ч.", "en": "Power-on time: {hours} h.", "zh": "通电时间：{hours} 小时。"}


def _texts(*parts: dict | None, **fmt) -> dict:
    """Join sentence dicts per language and add the Latin Uzbek copy."""
    out = {lang: ("" if lang == "zh" else " ").join(p[lang].format(**fmt) for p in parts if p) for lang in ("uz", "ru", "en", "zh")}
    out["uzl"] = translit(out["uz"])
    return {lang: out[lang] for lang in settings.langs if lang in out}


def _cap(gb: int) -> str:
    return f"{gb // 1000}TB" if gb >= 1000 else f"{gb}GB"


def _min_order(price: int) -> int:
    return 5 if price < 60 else (2 if price < 150 else 1)


async def _ensure_series(db, brand_id: int, name: str, color: str) -> None:
    """Add the series to the dictionary when it is missing; an existing entry (and a colour staff chose) stays as it is."""
    if await series_service.find(db, brand_id, name):
        return
    sort = (await db.scalar(select(func.max(Series.sort)).where(Series.brand_id == brand_id)) or 0) + 10
    db.add(Series(brand_id=brand_id, name=name, key=series_service.norm_key(name), color=color, sort=sort))
    await db.flush()
    print(f"  series added: {name} ({color})")


async def _ensure_model(db, brand_id: int, model: str, gb: int, iface: str, ff: str, series: str) -> None:
    key = model_dict.norm_key(model)
    if await db.scalar(select(BrandModel.id).where(BrandModel.brand_id == brand_id, BrandModel.key == key)):
        return
    db.add(BrandModel(brand_id=brand_id, name=model, key=key, capacity_gb=gb, interface=iface, form_factor=ff, series=series))


async def seed() -> None:
    rnd = random.Random(2026)  # same dates every run
    now = datetime.now(UTC)
    async with session_scope() as db:
        ids = list(await get_setting(db, IDS_KEY, []) or [])
        added = skipped = 0
        for color, rows in CATALOG.items():
            for brand_name, model, series, gb, rpm, cache, cond, price, stock, o in rows:
                brand = await brand_service.find_by_name(db, brand_name) or await brand_service.create_brand(db, name=brand_name)
                await _ensure_series(db, brand.id, series, color)
                iface, ff = o.get("iface", "SATA"), o.get("ff", "3.5")
                await _ensure_model(db, brand.id, model, gb, iface, ff, series)
                dup = await db.scalar(select(Product.id).where(Product.brand_id == brand.id, Product.model == model, Product.condition == cond))
                if dup:
                    skipped += 1
                    continue
                factory, specs = SERIES_INFO[(brand_name, series)]
                sw, fw = WARRANTY_DEFAULTS[cond]
                tested = cond != NEW or o.get("test") == "tested"
                test = TestStatus.TESTED if tested else TestStatus(o.get("test", "untested"))
                hours = o.get("hours")
                arrived = now - timedelta(days=rnd.randint(20, 45) if o.get("was") else rnd.randint(0, 50), hours=rnd.randint(0, 23))
                p = Product(
                    model=model, label_model=o.get("label"), series=series, capacity_gb=gb, interface=Interface(iface), form_factor=FormFactor(ff),
                    condition=cond, purposes=[x.value for x in PURPOSES[color]], color=await series_service.colour_for(db, brand.id, series, model),
                    rpm=rpm, cache_mb=cache, price=Decimal(price), currency="USD", cost_price=(Decimal(price) * Decimal("0.86")).quantize(Decimal("1")),
                    stock=stock, reserved=0, min_order=o.get("min", _min_order(price)), box_qty=20 if ff == "3.5" else 50, full_box_only=o.get("full_box", False),
                    seller_warranty_months=sw, factory_warranty_months=factory if cond == NEW else fw, test_status=test,
                    hours_used=hours, health=o.get("health") or ("100%" if tested else None),
                    test_summary=_texts(TESTED, HOURS if hours else None, hours=f"{hours:,}" if hours else "") if tested else {},
                    description=_texts(ABOUT[color], SMALL if ff == "2.5" else None, HYBRID if o.get("flash") else None, name=f"{SHORT[brand_name]} {series}", cap=_cap(gb), flash=o.get("flash", "")),
                    compatibility=_texts(COMPAT[(iface, ff)]),
                    specs={**specs, **({"Flash": o["flash"]} if o.get("flash") else {})},
                    delivery_note={}, is_active=True, sale_allowed=True, arrived_at=arrived, sort=0,
                )
                if p.color != color:
                    print(f"  note: {model} goes to {p.color} — the {series} series colour in the dictionary")
                brand_service.sync_product_brand(p, brand)
                db.add(p)
                await db.flush()
                if o.get("was"):  # listed at the old price, cut a few days ago → shows on Discounts with the old price struck through
                    db.add(PriceHistory(product_id=p.id, old_price=None, new_price=Decimal(o["was"]), currency="USD", note="created", created_at=arrived))
                    db.add(PriceHistory(product_id=p.id, old_price=Decimal(o["was"]), new_price=p.price, currency="USD", created_at=now - timedelta(days=rnd.randint(2, 9))))
                else:
                    db.add(PriceHistory(product_id=p.id, old_price=None, new_price=p.price, currency="USD", note="created", created_at=arrived))
                await audit.log(db, None, "product.create", "product", p.id, None, {**snapshot(p, PRODUCT_FIELDS), "source": "test catalog"})
                ids.append(p.id)
                added += 1
        await set_setting(db, IDS_KEY, ids, "Products added by scripts/seed_products.py (removed with --remove)")
    print(f"test catalogue: {added} added, {skipped} already there")


async def remove() -> None:
    async with session_scope() as db:
        ids = list(await get_setting(db, IDS_KEY, []) or [])
        deleted = hidden = 0
        for p in (await db.execute(select(Product).where(Product.id.in_(ids)))).scalars().unique().all():
            used = await db.scalar(select(exists().where(OrderItem.product_id == p.id))) or await db.scalar(select(exists().where(Auction.product_id == p.id)))
            if used:  # keep order / auction history readable
                p.is_active = False
                hidden += 1
            else:
                await db.delete(p)
                deleted += 1
        await set_setting(db, IDS_KEY, [], "Products added by scripts/seed_products.py (removed with --remove)")
    print(f"test catalogue removed: {deleted} deleted, {hidden} hidden (on orders or auctions)")


if __name__ == "__main__":
    asyncio.run(remove() if "--remove" in sys.argv else seed())
