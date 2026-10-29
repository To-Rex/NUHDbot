"""Seed reference data (countries, cities, articles, settings) and optional SAMPLE products.

    uv run python -m scripts.seed            # reference data only
    uv run python -m scripts.seed --demo     # + sample products with generated placeholder images (clearly marked SAMPLE)
"""
import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.enums import Condition, FormFactor, ImageKind, Interface, Purpose, TestStatus
from app.models import Article, City, Country, Product, ProductImage
from app.services.settings_service import DEFAULTS, set_setting

COUNTRIES = [
    ("UZ", {"uz": "Ўзбекистон", "ru": "Узбекистан", "en": "Uzbekistan"}, "🇺🇿", "+998", ["Toshkent", "Samarqand", "Buxoro", "Andijon", "Farg'ona", "Namangan", "Qarshi", "Nukus", "Urganch", "Termiz", "Jizzax", "Navoiy", "Guliston"]),
    ("KZ", {"uz": "Қозоғистон", "ru": "Казахстан", "en": "Kazakhstan"}, "🇰🇿", "+7", ["Almaty", "Astana", "Shymkent", "Karaganda", "Aktobe", "Taraz", "Pavlodar"]),
    ("KG", {"uz": "Қирғизистон", "ru": "Кыргызстан", "en": "Kyrgyzstan"}, "🇰🇬", "+996", ["Bishkek", "Osh", "Jalal-Abad", "Karakol"]),
    ("TJ", {"uz": "Тожикистон", "ru": "Таджикистан", "en": "Tajikistan"}, "🇹🇯", "+992", ["Dushanbe", "Khujand", "Bokhtar", "Kulob"]),
    ("TM", {"uz": "Туркманистон", "ru": "Туркменистан", "en": "Turkmenistan"}, "🇹🇲", "+993", ["Ashgabat", "Türkmenabat", "Daşoguz", "Mary"]),
    ("RU", {"uz": "Россия", "ru": "Россия", "en": "Russia"}, "🇷🇺", "+7", ["Moscow", "Saint Petersburg", "Novosibirsk", "Yekaterinburg", "Kazan"]),
    ("OT", {"uz": "Бошқа", "ru": "Другая", "en": "Other"}, "🌍", "", []),
]

ARTICLES = [
    {
        "slug": "choose-pc", "category": "choose", "icon": "💻", "sort": 1,
        "title": {"uz": "Компьютер учун HDD танлаш", "ru": "Как выбрать HDD для компьютера", "en": "Choosing an HDD for a PC"},
        "summary": {"uz": "Сиғим, тезлик ва нарх мувозанати", "ru": "Баланс объёма, скорости и цены", "en": "Balancing capacity, speed and price"},
        "body": {
            "uz": "<p>Оддий компьютер учун 3.5\" SATA дисклар энг қулай танлов. 7200 rpm тезлик ўйин ва иш учун мос, 5400 rpm эса тинчроқ ва камроқ қизийди.</p><ul><li><b>1–2TB</b> — ҳужжат ва фото учун етарли</li><li><b>4TB+</b> — видео архив ва ўйинлар</li></ul><p>WD Blue ва Seagate BarraCuda — классик «десктоп» сериялар.</p>",
            "ru": "<p>Для обычного ПК оптимальны 3.5\" SATA диски. 7200 rpm подходит для игр и работы, 5400 rpm тише и холоднее.</p><ul><li><b>1–2TB</b> — документы и фото</li><li><b>4TB+</b> — видеоархив и игры</li></ul><p>WD Blue и Seagate BarraCuda — классические «десктопные» серии.</p>",
            "en": "<p>For a regular desktop, 3.5\" SATA drives are the best fit. 7200 rpm suits gaming and work, 5400 rpm runs quieter and cooler.</p><ul><li><b>1–2TB</b> — documents and photos</li><li><b>4TB+</b> — video archives and games</li></ul><p>WD Blue and Seagate BarraCuda are the classic desktop lines.</p>",
        },
    },
    {
        "slug": "choose-cctv", "category": "choose", "icon": "📹", "sort": 2,
        "title": {"uz": "Видеокузатув учун HDD", "ru": "HDD для видеонаблюдения", "en": "HDDs for surveillance"},
        "summary": {"uz": "24/7 ёзишга мўлжалланган сериялар", "ru": "Серии для записи 24/7", "en": "Lines built for 24/7 recording"},
        "body": {
            "uz": "<p>Кузатув тизимлари дискка узлуксиз ёзади, шунинг учун махсус сериялар керак: <b>WD Purple</b>, <b>Seagate SkyHawk</b>, <b>Toshiba S300</b>. Улар кўп камерали оқимга ва юқори ҳароратга чидамли.</p><p>Сиғимни ҳисоблаш: камералар сони × битрейт × сақлаш кунлари. 8 камера, 4 Mbps, 30 кун ≈ 10TB.</p>",
            "ru": "<p>Системы наблюдения пишут на диск непрерывно, поэтому нужны специальные серии: <b>WD Purple</b>, <b>Seagate SkyHawk</b>, <b>Toshiba S300</b>. Они рассчитаны на многопоточную запись и нагрев.</p><p>Расчёт объёма: число камер × битрейт × дни хранения. 8 камер, 4 Mbps, 30 дней ≈ 10TB.</p>",
            "en": "<p>Surveillance systems write continuously, so use purpose-built lines: <b>WD Purple</b>, <b>Seagate SkyHawk</b>, <b>Toshiba S300</b>. They handle multi-stream writes and heat.</p><p>Capacity math: cameras × bitrate × retention days. 8 cameras, 4 Mbps, 30 days ≈ 10TB.</p>",
        },
    },
    {
        "slug": "choose-nas", "category": "choose", "icon": "🗄️", "sort": 3,
        "title": {"uz": "NAS ва сервер учун HDD", "ru": "HDD для NAS и серверов", "en": "HDDs for NAS and servers"},
        "summary": {"uz": "RAID, вибрация ва ишончлилик", "ru": "RAID, вибрация и надёжность", "en": "RAID, vibration and reliability"},
        "body": {
            "uz": "<p>NAS учун <b>WD Red / Red Pro</b>, <b>Seagate IronWolf</b>; сервер учун <b>WD Gold</b>, <b>Seagate Exos</b>, <b>Ultrastar</b>. Бу дисклар RAID массивда ишлашга, вибрация ва 24/7 юкламага мослашган. SAS интерфейс сервер контроллерлари учун.</p>",
            "ru": "<p>Для NAS — <b>WD Red / Red Pro</b>, <b>Seagate IronWolf</b>; для серверов — <b>WD Gold</b>, <b>Seagate Exos</b>, <b>Ultrastar</b>. Они рассчитаны на RAID, вибрацию и нагрузку 24/7. SAS — для серверных контроллеров.</p>",
            "en": "<p>For NAS use <b>WD Red / Red Pro</b> or <b>Seagate IronWolf</b>; for servers <b>WD Gold</b>, <b>Seagate Exos</b>, <b>Ultrastar</b>. They are designed for RAID, vibration and 24/7 load. SAS is for server controllers.</p>",
        },
    },
    {
        "slug": "sata-vs-sas", "category": "tech", "icon": "🔌", "sort": 4,
        "title": {"uz": "SATA ва SAS фарқи", "ru": "SATA и SAS: в чём разница", "en": "SATA vs SAS"},
        "summary": {"uz": "Қайси бири сизга керак?", "ru": "Какой нужен вам?", "en": "Which one do you need?"},
        "body": {
            "uz": "<p><b>SATA</b> — оддий компьютер, NAS ва кузатув учун универсал интерфейс. <b>SAS</b> — сервер контроллерлари учун, икки портли, ишончлироқ, лекин оддий материнская платага уланмайди. SAS контроллер SATA дискни қабул қилади, аксинча эмас.</p>",
            "ru": "<p><b>SATA</b> — универсальный интерфейс для ПК, NAS и наблюдения. <b>SAS</b> — для серверных контроллеров, двухпортовый и надёжнее, но не подключается к обычной материнской плате. SAS-контроллер принимает SATA-диски, обратное невозможно.</p>",
            "en": "<p><b>SATA</b> is the universal interface for PCs, NAS and surveillance. <b>SAS</b> is for server controllers: dual-ported and more robust, but it will not plug into a regular motherboard. A SAS controller accepts SATA drives, not vice versa.</p>",
        },
    },
    {
        "slug": "form-factor", "category": "tech", "icon": "📏", "sort": 5,
        "title": {"uz": "2.5\" ва 3.5\" фарқи", "ru": "2.5\" и 3.5\": отличия", "en": "2.5\" vs 3.5\""},
        "summary": {"uz": "Ўлчам, қувват ва сиғим", "ru": "Размер, питание и объём", "en": "Size, power and capacity"},
        "body": {
            "uz": "<p><b>3.5\"</b> — десктоп, NAS, сервер, кузатув; катта сиғим ва арзонроқ нарх. <b>2.5\"</b> — ноутбук ва компакт қурилмалар; камроқ қувват, одатда 5TB гача.</p>",
            "ru": "<p><b>3.5\"</b> — десктопы, NAS, серверы, наблюдение; больший объём и ниже цена за TB. <b>2.5\"</b> — ноутбуки и компактные устройства; меньше питания, обычно до 5TB.</p>",
            "en": "<p><b>3.5\"</b> — desktops, NAS, servers, surveillance; larger capacity and cheaper per TB. <b>2.5\"</b> — laptops and compact devices; lower power, usually up to 5TB.</p>",
        },
    },
    {
        "slug": "series-guide", "category": "tech", "icon": "🏷️", "sort": 6,
        "title": {"uz": "WD, Seagate, Toshiba сериялари", "ru": "Серии WD, Seagate, Toshiba", "en": "WD, Seagate, Toshiba lines"},
        "summary": {"uz": "Ранг ва ном нимани билдиради", "ru": "Что значат цвета и названия", "en": "What the colours and names mean"},
        "body": {
            "uz": "<table><tr><th>Вазифа</th><th>WD</th><th>Seagate</th><th>Toshiba</th></tr><tr><td>Десктоп</td><td>Blue</td><td>BarraCuda</td><td>P300</td></tr><tr><td>Кузатув</td><td>Purple</td><td>SkyHawk</td><td>S300</td></tr><tr><td>NAS</td><td>Red / Red Pro</td><td>IronWolf / Pro</td><td>N300</td></tr><tr><td>Сервер</td><td>Gold / Ultrastar</td><td>Exos</td><td>MG серияси</td></tr></table>",
            "ru": "<table><tr><th>Назначение</th><th>WD</th><th>Seagate</th><th>Toshiba</th></tr><tr><td>Десктоп</td><td>Blue</td><td>BarraCuda</td><td>P300</td></tr><tr><td>Наблюдение</td><td>Purple</td><td>SkyHawk</td><td>S300</td></tr><tr><td>NAS</td><td>Red / Red Pro</td><td>IronWolf / Pro</td><td>N300</td></tr><tr><td>Сервер</td><td>Gold / Ultrastar</td><td>Exos</td><td>Серия MG</td></tr></table>",
            "en": "<table><tr><th>Use</th><th>WD</th><th>Seagate</th><th>Toshiba</th></tr><tr><td>Desktop</td><td>Blue</td><td>BarraCuda</td><td>P300</td></tr><tr><td>Surveillance</td><td>Purple</td><td>SkyHawk</td><td>S300</td></tr><tr><td>NAS</td><td>Red / Red Pro</td><td>IronWolf / Pro</td><td>N300</td></tr><tr><td>Server</td><td>Gold / Ultrastar</td><td>Exos</td><td>MG series</td></tr></table>",
        },
    },
    {
        "slug": "new-used-refresh", "category": "conditions", "icon": "🏁", "sort": 7,
        "title": {"uz": "New / Used / Refresh фарқи", "ru": "New / Used / Refresh: разница", "en": "New vs Used vs Refresh"},
        "summary": {"uz": "Ҳар бир ҳолат нимани англатади", "ru": "Что означает каждое состояние", "en": "What each condition means"},
        "body": {
            "uz": "<p><b>New</b> — янги, ишлатилмаган диск, завод кафолати бўлиши мумкин.</p><p><b>Used</b> — аввал ишлатилган диск. Ишлаган соати ва SMART ҳолати карточкада кўрсатилади.</p><p><b>Refresh</b> — завод ёрлиғи (наклейкаси) алмаштирилган диск. Баъзан арзонроқ моделга қимматроқ модель ёрлиғи ёпиштирилган бўлади. Биз буни яширмаймиз: карточкада <i>ҳақиқий модель</i> ва <i>ёрлиқдаги модель</i> алоҳида ёзилади. Refresh — бу Refurbished (заводда қайта тикланган) дегани эмас.</p>",
            "ru": "<p><b>New</b> — новый, не использованный диск, возможна заводская гарантия.</p><p><b>Used</b> — бывший в употреблении. Наработка и SMART указаны в карточке.</p><p><b>Refresh</b> — диск с заменённой заводской наклейкой. Иногда на более дешёвую модель наклеена этикетка более дорогой. Мы этого не скрываем: в карточке отдельно указаны <i>реальная модель</i> и <i>модель на наклейке</i>. Refresh — это не Refurbished.</p>",
            "en": "<p><b>New</b> — brand new, unused, may carry a factory warranty.</p><p><b>Used</b> — previously used. Power-on hours and SMART status are shown on the card.</p><p><b>Refresh</b> — a drive whose factory label has been replaced. Sometimes a cheaper model carries a pricier model's label. We never hide it: the card lists the <i>real model</i> and the <i>label model</i> separately. Refresh is not the same as Refurbished.</p>",
        },
    },
    {
        "slug": "smart-health", "category": "tech", "icon": "🩺", "sort": 8,
        "title": {"uz": "SMART, Health, соат ва Bad sector", "ru": "SMART, Health, наработка и Bad sector", "en": "SMART, Health, hours and bad sectors"},
        "summary": {"uz": "Тест натижаларини қандай ўқиш", "ru": "Как читать результаты теста", "en": "How to read test results"},
        "body": {
            "uz": "<p><b>SMART</b> — дискнинг ўз-ўзини назорат қилиш тизими. <b>Health</b> — дастурлар (CrystalDiskInfo, HD Sentinel) берадиган умумий баҳо. <b>Ишлаган соати</b> (Power-On Hours) — диск қанча вақт ишлагани. <b>Bad sector</b> — ўқиб бўлмайдиган секторлар; Reallocated ва Pending қийматларига эътибор беринг.</p><p>Биз текширилган дискларда MHDD/Victoria скриншотларини буюртмага илова қиламиз.</p>",
            "ru": "<p><b>SMART</b> — система самодиагностики диска. <b>Health</b> — общая оценка из программ (CrystalDiskInfo, HD Sentinel). <b>Наработка</b> (Power-On Hours) — сколько диск проработал. <b>Bad sector</b> — нечитаемые сектора; смотрите Reallocated и Pending.</p><p>Для проверенных дисков мы прикладываем скриншоты MHDD/Victoria к заказу.</p>",
            "en": "<p><b>SMART</b> is the drive's self-monitoring system. <b>Health</b> is the overall score from tools like CrystalDiskInfo or HD Sentinel. <b>Power-On Hours</b> show how long the drive has run. <b>Bad sectors</b> are unreadable sectors — watch Reallocated and Pending counts.</p><p>For tested drives we attach MHDD/Victoria screenshots to your order.</p>",
        },
    },
    {
        "slug": "mhdd-testing", "category": "tech", "icon": "🧪", "sort": 9,
        "title": {"uz": "MHDD ва тест усуллари", "ru": "MHDD и методы тестирования", "en": "MHDD and test methods"},
        "summary": {"uz": "Биз дискларни қандай текширамиз", "ru": "Как мы проверяем диски", "en": "How we test drives"},
        "body": {
            "uz": "<p>Ҳар бир диск учун: SMART ўқиш → сиртни сканерлаш (MHDD/Victoria) → натижа скриншоти → серийный рақам билан боғлаш. Секин ёки хато секторли дисклар сотиладиган партиядан чиқарилади.</p>",
            "ru": "<p>Для каждого диска: чтение SMART → сканирование поверхности (MHDD/Victoria) → скриншот результата → привязка к серийному номеру. Диски с медленными или сбойными секторами исключаются из продажи.</p>",
            "en": "<p>For each drive: read SMART → surface scan (MHDD/Victoria) → screenshot of the result → link to the serial number. Drives with slow or failing sectors are removed from sale.</p>",
        },
    },
    {
        "slug": "install-accept", "category": "guide", "icon": "📦", "sort": 10,
        "title": {"uz": "HDD ўрнатиш ва қабул қилиш", "ru": "Установка и приёмка HDD", "en": "Installing and accepting HDDs"},
        "summary": {"uz": "Юкни олгач нима қилиш керак", "ru": "Что делать после получения груза", "en": "What to do when the shipment arrives"},
        "body": {
            "uz": "<ol><li>Қутини очишдан олдин ёрлиқ ва карго кодини суратга олинг.</li><li>Серийный рақамларни буюртмадаги рўйхат билан солиштиринг.</li><li>Дискларни статик электрдан ҳимояланг, тушириб юборманг.</li><li>Биринчи уланишда SMART ҳолатини текширинг.</li><li>Муаммо бўлса — 48 соат ичида бот орқали фото/видео билан мурожаат қилинг.</li></ol>",
            "ru": "<ol><li>Перед вскрытием сфотографируйте этикетку и карго-код.</li><li>Сверьте серийные номера со списком в заказе.</li><li>Берегите диски от статики и ударов.</li><li>При первом подключении проверьте SMART.</li><li>При проблеме — напишите в бот с фото/видео в течение 48 часов.</li></ol>",
            "en": "<ol><li>Photograph the label and cargo code before opening.</li><li>Match serial numbers against the list in your order.</li><li>Protect drives from static and drops.</li><li>Check SMART on first power-up.</li><li>If anything is wrong, message us via the bot with photos/video within 48 hours.</li></ol>",
        },
    },
    {
        "slug": "warranty-check", "category": "guide", "icon": "🔎", "sort": 11,
        "title": {"uz": "Расмий кафолатни текшириш", "ru": "Проверка официальной гарантии", "en": "Checking the official warranty"},
        "summary": {"uz": "WD ва Seagate сайтларида серийный рақам", "ru": "Серийный номер на сайтах WD и Seagate", "en": "Serial lookup on WD and Seagate sites"},
        "body": {
            "uz": "<p>WD: <a href=\"https://support-en.wd.com/app/warrantystatusweb\" target=\"_blank\">warranty status</a>. Seagate: <a href=\"https://www.seagate.com/support/warranty-and-replacements/\" target=\"_blank\">warranty check</a>.</p><p><b>Муҳим:</b> расмий сайтда текшириш дискнинг оригиналлигини 100% исботламайди, натижа чиқмаслиги эса автоматик равишда диск сохта дегани эмас (айниқса OEM ва Refresh дискларда).</p>",
            "ru": "<p>WD: <a href=\"https://support-en.wd.com/app/warrantystatusweb\" target=\"_blank\">warranty status</a>. Seagate: <a href=\"https://www.seagate.com/support/warranty-and-replacements/\" target=\"_blank\">warranty check</a>.</p><p><b>Важно:</b> проверка на сайте не доказывает оригинальность на 100%, а отсутствие результата не означает, что диск поддельный (особенно для OEM и Refresh).</p>",
            "en": "<p>WD: <a href=\"https://support-en.wd.com/app/warrantystatusweb\" target=\"_blank\">warranty status</a>. Seagate: <a href=\"https://www.seagate.com/support/warranty-and-replacements/\" target=\"_blank\">warranty check</a>.</p><p><b>Important:</b> an official lookup does not prove authenticity 100%, and a missing result does not automatically mean the drive is fake (especially OEM and Refresh units).</p>",
        },
    },
]

DEMO_PRODUCTS = [
    ("Western Digital", "WD40PURZ", "Purple", 4000, Condition.NEW, 68, 120, 5, 20, [Purpose.CCTV], TestStatus.TESTED, 12, 36, None),
    ("Western Digital", "WD20EZAZ", "Blue", 2000, Condition.NEW, 41, 60, 5, 20, [Purpose.PC], TestStatus.UNTESTED, 12, 24, None),
    ("Seagate", "ST4000VX016", "SkyHawk", 4000, Condition.USED, 46, 85, 10, 20, [Purpose.CCTV], TestStatus.TESTED, 6, 0, 18420),
    ("Seagate", "ST8000VE001", "SkyHawk AI", 8000, Condition.NEW, 139, 30, 2, 10, [Purpose.CCTV, Purpose.NAS], TestStatus.TESTING, 12, 36, None),
    ("Toshiba", "HDWT140UZSVA", "S300", 4000, Condition.REFRESH, 39, 200, 10, 20, [Purpose.CCTV], TestStatus.TESTED, 6, 0, 9800),
    ("HGST", "HUS726060ALE610", "Ultrastar 7K6", 6000, Condition.USED, 58, 40, 4, 20, [Purpose.SERVER, Purpose.NAS], TestStatus.TESTED, 6, 0, 31200),
    ("Seagate", "ST12000NM0008", "Exos X14", 12000, Condition.USED, 142, 24, 2, 10, [Purpose.SERVER, Purpose.STORAGE], TestStatus.TESTED, 6, 0, 26500),
    ("Western Digital", "WD102KRYZ", "Gold", 10000, Condition.NEW, 229, 12, 1, 10, [Purpose.SERVER], TestStatus.UNTESTED, 12, 60, None),
    ("Seagate", "ST1000DM010", "BarraCuda", 1000, Condition.NEW, 29, 300, 10, 20, [Purpose.PC], TestStatus.UNTESTED, 12, 24, None),
    ("Western Digital", "WD10EZEX", "Blue", 1000, Condition.USED, 17, 140, 10, 20, [Purpose.PC], TestStatus.TESTED, 6, 0, 14100),
    ("Hikvision", "HK-ST4000VX", "Surveillance", 4000, Condition.REFRESH, 36, 0, 10, 20, [Purpose.CCTV], TestStatus.TESTED, 6, 0, 12000),
    ("Dahua", "DHI-ST2000VX015", "Surveillance", 2000, Condition.NEW, 38, 75, 5, 20, [Purpose.CCTV], TestStatus.UNTESTED, 12, 24, None),
    ("Toshiba", "MG08ADA800E", "MG08", 8000, Condition.NEW, 149, 18, 1, 10, [Purpose.SERVER, Purpose.NAS], TestStatus.UNTESTED, 12, 60, None),
    ("Seagate", "ST2000LM015", "BarraCuda 2.5", 2000, Condition.NEW, 52, 44, 5, 20, [Purpose.PC, Purpose.STORAGE], TestStatus.UNTESTED, 12, 24, None),
]

BRAND_COLORS = {"Western Digital": ("#1b2a66", "#5c84ff"), "Seagate": ("#0f5132", "#4ade80"), "Toshiba": ("#7c2d12", "#fb923c"), "HGST": ("#312e81", "#a5b4fc"), "Hikvision": ("#7f1d1d", "#f87171"), "Dahua": ("#1e3a5f", "#7dd3fc")}


def _demo_image(brand: str, model: str, capacity: str, idx: int) -> dict:
    """Generate a clean, clearly-labelled SAMPLE cover image (never passed off as a real photo)."""
    size = 800
    c1, c2 = BRAND_COLORS.get(brand, ("#334155", "#94a3b8"))
    img = Image.new("RGB", (size, size), c1)
    d = ImageDraw.Draw(img)
    # flat brand-coloured background with a lighter inset frame (no gradients, by design rule)
    d.rounded_rectangle((28, 28, size - 28, size - 28), radius=36, outline=c2, width=3)
    # stylised drive
    d.rounded_rectangle((150, 120, 650, 680), radius=40, fill=(20, 24, 36), outline=(255, 255, 255), width=4)
    d.ellipse((230, 220, 570, 560), fill=(60, 66, 84), outline=(200, 205, 220), width=6)
    d.ellipse((360, 350, 440, 430), fill=(230, 232, 240))
    d.line((400, 390, 560, 300), fill=(255, 122, 26), width=14)
    try:
        f_big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 56)
        f_mid = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 34)
    except OSError:
        f_big = f_mid = ImageFont.load_default()
    d.text((400, 620), capacity, fill="white", font=f_big, anchor="mm")
    d.text((400, 735), f"{brand} {model}", fill="white", font=f_mid, anchor="mm")
    d.rounded_rectangle((20, 20, 230, 70), radius=14, fill=(255, 255, 255))
    d.text((125, 45), "SAMPLE", fill=(220, 38, 38), font=f_mid, anchor="mm")
    name = f"demo_{idx}.webp"
    thumb = f"demo_{idx}_t.webp"
    img.save(settings.upload_dir / name, "WEBP", quality=82)
    im2 = img.copy()
    im2.thumbnail((480, 480))
    im2.save(settings.upload_dir / thumb, "WEBP", quality=78)
    return {"filename": name, "thumb": thumb, "width": size, "height": size}


async def seed_reference() -> None:
    async with session_scope() as db:
        for code, name, flag, phone, cities in COUNTRIES:
            c = await db.get(Country, code)
            if c is None:
                db.add(Country(code=code, name=name, flag=flag, phone_code=phone, sort=COUNTRIES.index((code, name, flag, phone, cities))))
                await db.flush()
                for i, city in enumerate(cities):
                    db.add(City(country_code=code, name={"uz": city, "ru": city, "en": city}, sort=i))
        for a in ARTICLES:
            existing = (await db.execute(select(Article).where(Article.slug == a["slug"]))).scalar_one_or_none()
            if existing is None:
                db.add(Article(**a))
            else:
                for k, v in a.items():
                    setattr(existing, k, v)
        for key, spec in DEFAULTS.items():
            from app.models import Setting

            if await db.get(Setting, key) is None:
                await set_setting(db, key, spec["v"], spec["d"])
    print("reference data ready")


async def seed_demo() -> None:
    async with session_scope() as db:
        count = (await db.execute(select(Product))).scalars().first()
        if count is not None:
            print("products already exist; skipping demo")
            return
        now = datetime.now(UTC)
        for i, row in enumerate(DEMO_PRODUCTS):
            brand, model, series, gb, cond, price, stock, min_order, box, purposes, test, sw, fw, hours = row
            cap = f"{gb // 1000}TB" if gb >= 1000 else f"{gb}GB"
            p = Product(
                brand=brand, model=model, series=series, capacity_gb=gb,
                interface=Interface.SAS if "HUS" in model else Interface.SATA,
                form_factor=FormFactor.F25 if "LM015" in model else FormFactor.F35,
                condition=cond, purposes=[x.value for x in purposes], price=price, currency="USD", stock=stock,
                min_order=min_order, box_qty=box, seller_warranty_months=sw, factory_warranty_months=fw, test_status=test,
                hours_used=hours, health=("Good" if test == TestStatus.TESTED else None),
                label_model=(f"{model}-LBL" if cond == Condition.REFRESH else None),
                rpm=7200 if "Exos" in (series or "") or "Gold" in (series or "") or "Ultrastar" in (series or "") else 5400,
                cache_mb=256 if gb >= 8000 else 64,
                description={
                    "uz": f"{brand} {series} сериясидаги {cap} диск. НАМУНА маълумот — реал партия маълумотлари админ томонидан киритилади.",
                    "ru": f"Диск {brand} {series} {cap}. ОБРАЗЕЦ — реальные данные партии вносит администратор.",
                    "en": f"{brand} {series} {cap} drive. SAMPLE data — real batch data is entered by the admin.",
                },
                compatibility={"uz": "SATA III порт, стандарт 3.5\" ўрин", "ru": "Порт SATA III, стандартный отсек 3.5\"", "en": "SATA III port, standard 3.5\" bay"},
                specs={"RPM": "7200" if gb >= 8000 else "5400", "Cache": f"{256 if gb >= 8000 else 64} MB", "Interface": "SATA 6Gb/s"},
                arrived_at=now - timedelta(days=random.randint(0, 40)),
                sort=len(DEMO_PRODUCTS) - i,
            )
            db.add(p)
            await db.flush()
            meta = _demo_image(brand, model, cap, i)
            db.add(ProductImage(product_id=p.id, kind=ImageKind.SAMPLE, is_cover=True, sort=0, **meta))
    print("demo products ready")


async def main() -> None:
    await seed_reference()
    if "--demo" in sys.argv:
        await seed_demo()


if __name__ == "__main__":
    asyncio.run(main())
