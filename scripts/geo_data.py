"""Reference geography: countries → regions → cities, used by the idempotent seed.

Shape: COUNTRY = (code, flag, phone, names{uz,uzl,ru,en,zh}, regions)
       region  = ((latin, ru, en?), [city, ...])     city = (latin, ru, en?)   — en defaults to latin.
Uzbek Cyrillic city/region names are derived: for UZ by transliterating the Latin form,
for every other country the Russian spelling is used (standard practice in Uzbek Cyrillic).
"""

C = lambda latin, ru, en=None: (latin, ru, en or latin)  # noqa: E731

UZ = [
    (C("Toshkent shahri", "город Ташкент", "Tashkent City"), [C("Toshkent", "Ташкент", "Tashkent")]),
    (C("Toshkent viloyati", "Ташкентская область", "Tashkent Region"), [
        C("Nurafshon", "Нурафшон"), C("Chirchiq", "Чирчик", "Chirchik"), C("Angren", "Ангрен"), C("Olmaliq", "Алмалык", "Almalyk"),
        C("Bekobod", "Бекабад", "Bekabad"), C("Yangiyo'l", "Янгиюль", "Yangiyul"), C("Ohangaron", "Ахангаран", "Akhangaran"),
        C("Parkent", "Паркент"), C("G'azalkent", "Газалкент", "Gazalkent"), C("Keles", "Келес"), C("Zangiota", "Зангиата"), C("Qibray", "Кибрай", "Kibray"),
        C("Piskent", "Пскент"), C("Bo'ka", "Бука", "Buka"), C("Chinoz", "Чиназ", "Chinaz"), C("Oqqo'rg'on", "Аккурган", "Akkurgan"),
    ]),
    (C("Andijon viloyati", "Андижанская область", "Andijan Region"), [
        C("Andijon", "Андижан", "Andijan"), C("Asaka", "Асака"), C("Xonobod", "Ханабад", "Khanabad"), C("Shahrixon", "Шахрихан", "Shahrikhan"),
        C("Qo'rg'ontepa", "Кургантепа", "Kurgantepa"), C("Marhamat", "Мархамат"), C("Paxtaobod", "Пахтаабад", "Pakhtaabad"), C("Xo'jaobod", "Ходжаабад", "Khojaabad"),
        C("Baliqchi", "Балыкчи", "Balikchi"), C("Jalaquduq", "Джалакудук", "Jalakuduk"), C("Oltinko'l", "Алтынкуль", "Altynkul"),
    ]),
    (C("Buxoro viloyati", "Бухарская область", "Bukhara Region"), [
        C("Buxoro", "Бухара", "Bukhara"), C("Kogon", "Каган", "Kagan"), C("G'ijduvon", "Гиждуван", "Gijduvan"), C("Vobkent", "Вабкент", "Vabkent"),
        C("Romitan", "Ромитан"), C("Shofirkon", "Шафиркан", "Shafirkan"), C("Qorako'l", "Каракуль", "Karakul"), C("Olot", "Алат", "Alat"), C("Jondor", "Жондор"), C("Qorovulbozor", "Караулбазар", "Karaulbazar"),
    ]),
    (C("Farg'ona viloyati", "Ферганская область", "Fergana Region"), [
        C("Farg'ona", "Фергана", "Fergana"), C("Qo'qon", "Коканд", "Kokand"), C("Marg'ilon", "Маргилан", "Margilan"), C("Quvasoy", "Кувасай", "Kuvasay"),
        C("Rishton", "Риштан", "Rishtan"), C("Quva", "Кува", "Kuva"), C("Beshariq", "Бешарык", "Besharyk"), C("Oltiariq", "Алтыарык", "Altyaryk"),
        C("Bag'dod", "Багдад", "Bagdad"), C("Yaypan", "Яйпан"), C("Toshloq", "Ташлак", "Tashlak"), C("Dang'ara", "Дангара", "Dangara"),
    ]),
    (C("Jizzax viloyati", "Джизакская область", "Jizzakh Region"), [
        C("Jizzax", "Джизак", "Jizzakh"), C("Zomin", "Заамин", "Zaamin"), C("G'allaorol", "Галляарал", "Gallaaral"), C("Paxtakor", "Пахтакор"),
        C("Do'stlik", "Дустлик", "Dustlik"), C("Forish", "Фариш"), C("Zarbdor", "Зарбдар"), C("Yangiobod", "Янгиабад"),
    ]),
    (C("Namangan viloyati", "Наманганская область", "Namangan Region"), [
        C("Namangan", "Наманган"), C("Chust", "Чуст"), C("Pop", "Пап", "Pap"), C("Kosonsoy", "Касансай", "Kasansay"), C("To'raqo'rg'on", "Туракурган", "Turakurgan"),
        C("Uchqo'rg'on", "Учкурган", "Uchkurgan"), C("Chortoq", "Чартак", "Chartak"), C("Haqqulobod", "Хаккулабад", "Khakkulabad"), C("Yangiqo'rg'on", "Янгикурган", "Yangikurgan"),
    ]),
    (C("Navoiy viloyati", "Навоийская область", "Navoi Region"), [
        C("Navoiy", "Навои", "Navoi"), C("Zarafshon", "Зарафшан", "Zarafshan"), C("Uchquduq", "Учкудук", "Uchkuduk"), C("Nurota", "Нурата", "Nurata"),
        C("Karmana", "Кармана"), C("Qiziltepa", "Кызылтепа", "Kyzyltepa"), C("Konimex", "Канимех", "Kanimekh"), C("Yangirabot", "Янгирабад", "Yangirabad"),
    ]),
    (C("Qashqadaryo viloyati", "Кашкадарьинская область", "Kashkadarya Region"), [
        C("Qarshi", "Карши", "Karshi"), C("Shahrisabz", "Шахрисабз", "Shakhrisabz"), C("Kitob", "Китаб", "Kitab"), C("Koson", "Касан", "Kasan"),
        C("Muborak", "Мубарек", "Mubarek"), C("G'uzor", "Гузар", "Guzar"), C("Yakkabog'", "Яккабаг", "Yakkabag"), C("Chiroqchi", "Чиракчи", "Chirakchi"),
        C("Kamashi", "Камаши"), C("Dehqonobod", "Дехканабад", "Dekhkanabad"), C("Nishon", "Нишан", "Nishan"),
    ]),
    (C("Qoraqalpog'iston Respublikasi", "Республика Каракалпакстан", "Republic of Karakalpakstan"), [
        C("Nukus", "Нукус"), C("Xo'jayli", "Ходжейли", "Khodjeyli"), C("To'rtko'l", "Турткуль", "Turtkul"), C("Beruniy", "Беруни", "Beruni"),
        C("Taxiatosh", "Тахиаташ", "Takhiatash"), C("Qo'ng'irot", "Кунград", "Kungrad"), C("Chimboy", "Чимбай", "Chimbay"), C("Mo'ynoq", "Муйнак", "Muynak"),
        C("Kegeyli", "Кегейли"), C("Mang'it", "Мангит", "Mangit"), C("Taxtako'pir", "Тахтакупыр", "Takhtakupyr"),
    ]),
    (C("Samarqand viloyati", "Самаркандская область", "Samarkand Region"), [
        C("Samarqand", "Самарканд", "Samarkand"), C("Kattaqo'rg'on", "Каттакурган", "Kattakurgan"), C("Urgut", "Ургут"), C("Jomboy", "Джамбай", "Jambay"),
        C("Bulung'ur", "Булунгур", "Bulungur"), C("Ishtixon", "Иштыхан", "Ishtykhan"), C("Oqtosh", "Акташ", "Aktash"), C("Payariq", "Пайарык", "Payaryk"),
        C("Nurobod", "Нурабад", "Nurabad"), C("Toyloq", "Тайлак", "Taylak"), C("Chelak", "Челек"), C("Juma", "Джума", "Juma"),
    ]),
    (C("Sirdaryo viloyati", "Сырдарьинская область", "Syrdarya Region"), [
        C("Guliston", "Гулистан", "Gulistan"), C("Yangiyer", "Янгиер"), C("Shirin", "Ширин"), C("Sirdaryo", "Сырдарья", "Syrdarya"),
        C("Boyovut", "Баяут", "Bayaut"), C("Xovos", "Хаваст", "Khavast"), C("Sardoba", "Сардоба"),
    ]),
    (C("Surxondaryo viloyati", "Сурхандарьинская область", "Surkhandarya Region"), [
        C("Termiz", "Термез", "Termez"), C("Denov", "Денау", "Denau"), C("Sherobod", "Шерабад", "Sherabad"), C("Boysun", "Байсун", "Baysun"),
        C("Jarqo'rg'on", "Джаркурган", "Jarkurgan"), C("Sho'rchi", "Шурчи", "Shurchi"), C("Qumqo'rg'on", "Кумкурган", "Kumkurgan"), C("Angor", "Ангор"), C("Sariosiyo", "Сариасия", "Sariasiya"),
    ]),
    (C("Xorazm viloyati", "Хорезмская область", "Khorezm Region"), [
        C("Urganch", "Ургенч", "Urgench"), C("Xiva", "Хива", "Khiva"), C("Hazorasp", "Хазарасп", "Khazarasp"), C("Shovot", "Шават", "Shavat"),
        C("Gurlan", "Гурлен", "Gurlen"), C("Xonqa", "Ханка", "Khanka"), C("Bog'ot", "Багат", "Bagat"), C("Yangibozor", "Янгибазар", "Yangibazar"), C("Pitnak", "Питнак"),
    ]),
]

KZ = [
    (C("Respublika ahamiyatidagi shaharlar", "Города республиканского значения", "Cities of republican significance"), [
        C("Almaty", "Алматы"), C("Astana", "Астана"), C("Shymkent", "Шымкент"),
    ]),
    (C("Abay viloyati", "Абайская область", "Abai Region"), [C("Semey", "Семей"), C("Kurchatov", "Курчатов"), C("Ayagoz", "Аягоз")]),
    (C("Aqmola viloyati", "Акмолинская область", "Akmola Region"), [C("Kokshetau", "Кокшетау"), C("Stepnogorsk", "Степногорск"), C("Shchuchinsk", "Щучинск")]),
    (C("Aqto'be viloyati", "Актюбинская область", "Aktobe Region"), [C("Aktobe", "Актобе"), C("Khromtau", "Хромтау"), C("Kandyagash", "Кандыагаш")]),
    (C("Almaty viloyati", "Алматинская область", "Almaty Region"), [C("Konaev", "Конаев"), C("Talgar", "Талгар"), C("Kaskelen", "Каскелен"), C("Esik", "Есик")]),
    (C("Atyrau viloyati", "Атырауская область", "Atyrau Region"), [C("Atyrau", "Атырау"), C("Kulsary", "Кульсары")]),
    (C("Sharqiy Qozog'iston viloyati", "Восточно-Казахстанская область", "East Kazakhstan Region"), [C("Oskemen", "Усть-Каменогорск", "Oskemen"), C("Ridder", "Риддер"), C("Altai", "Алтай")]),
    (C("Jambil viloyati", "Жамбылская область", "Jambyl Region"), [C("Taraz", "Тараз"), C("Shu", "Шу"), C("Karatau", "Каратау")]),
    (C("Jetisu viloyati", "Жетысуская область", "Jetisu Region"), [C("Taldykorgan", "Талдыкорган"), C("Tekeli", "Текели"), C("Zharkent", "Жаркент")]),
    (C("G'arbiy Qozog'iston viloyati", "Западно-Казахстанская область", "West Kazakhstan Region"), [C("Oral", "Уральск", "Oral"), C("Aksay", "Аксай")]),
    (C("Qarag'andi viloyati", "Карагандинская область", "Karaganda Region"), [C("Karaganda", "Караганда"), C("Temirtau", "Темиртау"), C("Saran", "Сарань"), C("Balkhash", "Балхаш")]),
    (C("Qostanay viloyati", "Костанайская область", "Kostanay Region"), [C("Kostanay", "Костанай"), C("Rudny", "Рудный"), C("Lisakovsk", "Лисаковск")]),
    (C("Qizilo'rda viloyati", "Кызылординская область", "Kyzylorda Region"), [C("Kyzylorda", "Кызылорда"), C("Baikonur", "Байконур"), C("Aral", "Аральск", "Aral")]),
    (C("Mang'istau viloyati", "Мангистауская область", "Mangystau Region"), [C("Aktau", "Актау"), C("Zhanaozen", "Жанаозен"), C("Beyneu", "Бейнеу")]),
    (C("Pavlodar viloyati", "Павлодарская область", "Pavlodar Region"), [C("Pavlodar", "Павлодар"), C("Ekibastuz", "Экибастуз"), C("Aksu", "Аксу")]),
    (C("Shimoliy Qozog'iston viloyati", "Северо-Казахстанская область", "North Kazakhstan Region"), [C("Petropavl", "Петропавловск", "Petropavl")]),
    (C("Turkiston viloyati", "Туркестанская область", "Turkistan Region"), [C("Turkistan", "Туркестан"), C("Kentau", "Кентау"), C("Saryagash", "Сарыагаш"), C("Arys", "Арыс"), C("Zhetysai", "Жетысай")]),
    (C("Ulitau viloyati", "Улытауская область", "Ulytau Region"), [C("Zhezkazgan", "Жезказган"), C("Satpayev", "Сатпаев")]),
]

KG = [
    (C("Bishkek shahri", "город Бишкек", "Bishkek City"), [C("Bishkek", "Бишкек")]),
    (C("O'sh shahri", "город Ош", "Osh City"), [C("Osh", "Ош")]),
    (C("Chuy viloyati", "Чуйская область", "Chuy Region"), [C("Tokmok", "Токмок"), C("Kant", "Кант"), C("Kara-Balta", "Кара-Балта"), C("Shopokov", "Шопоков")]),
    (C("O'sh viloyati", "Ошская область", "Osh Region"), [C("Uzgen", "Узген"), C("Kara-Suu", "Кара-Суу"), C("Nookat", "Ноокат")]),
    (C("Jalolobod viloyati", "Джалал-Абадская область", "Jalal-Abad Region"), [C("Jalal-Abad", "Джалал-Абад"), C("Kerben", "Кербен"), C("Tash-Kumyr", "Таш-Кумыр"), C("Mailuu-Suu", "Майлуу-Суу"), C("Kochkor-Ata", "Кочкор-Ата")]),
    (C("Issiqko'l viloyati", "Иссык-Кульская область", "Issyk-Kul Region"), [C("Karakol", "Каракол"), C("Balykchy", "Балыкчы"), C("Cholpon-Ata", "Чолпон-Ата")]),
    (C("Norin viloyati", "Нарынская область", "Naryn Region"), [C("Naryn", "Нарын"), C("At-Bashi", "Ат-Башы")]),
    (C("Talas viloyati", "Таласская область", "Talas Region"), [C("Talas", "Талас")]),
    (C("Botken viloyati", "Баткенская область", "Batken Region"), [C("Batken", "Баткен"), C("Kyzyl-Kiya", "Кызыл-Кия"), C("Sulukta", "Сулюкта"), C("Isfana", "Исфана")]),
]

TJ = [
    (C("Dushanbe shahri", "город Душанбе", "Dushanbe City"), [C("Dushanbe", "Душанбе")]),
    (C("Sug'd viloyati", "Согдийская область", "Sughd Region"), [C("Khujand", "Худжанд"), C("Istaravshan", "Истаравшан"), C("Panjakent", "Пенджикент", "Panjakent"), C("Isfara", "Исфара"), C("Konibodom", "Канибадам", "Konibodom"), C("Guliston", "Гулистон"), C("Buston", "Бустон"), C("Istiklol", "Истиклол")]),
    (C("Xatlon viloyati", "Хатлонская область", "Khatlon Region"), [C("Bokhtar", "Бохтар"), C("Kulob", "Куляб", "Kulob"), C("Danghara", "Дангара"), C("Norak", "Нурек", "Norak"), C("Levakant", "Левакант"), C("Farkhor", "Фархор")]),
    (C("Tog'li Badaxshon", "Горно-Бадахшанская АО", "Gorno-Badakhshan"), [C("Khorugh", "Хорог", "Khorugh"), C("Murghob", "Мургаб", "Murghob")]),
    (C("Respublika bo'ysunuvidagi tumanlar", "Районы республиканского подчинения", "Districts of Republican Subordination"), [C("Hisor", "Гиссар", "Hisor"), C("Vahdat", "Вахдат"), C("Tursunzoda", "Турсунзаде", "Tursunzoda"), C("Rogun", "Рогун"), C("Rasht", "Рашт")]),
]

TM = [
    (C("Ashxobod shahri", "город Ашхабад", "Ashgabat City"), [C("Ashgabat", "Ашхабад")]),
    (C("Ahal viloyati", "Ахалский велаят", "Ahal Region"), [C("Arkadag", "Аркадаг"), C("Anau", "Анау"), C("Tejen", "Теджен")]),
    (C("Balkan viloyati", "Балканский велаят", "Balkan Region"), [C("Balkanabat", "Балканабат"), C("Turkmenbashi", "Туркменбаши")]),
    (C("Dashoguz viloyati", "Дашогузский велаят", "Dashoguz Region"), [C("Dashoguz", "Дашогуз"), C("Koneurgench", "Кёнеургенч")]),
    (C("Lebap viloyati", "Лебапский велаят", "Lebap Region"), [C("Turkmenabat", "Туркменабат"), C("Kerki", "Керки")]),
    (C("Mari viloyati", "Марыйский велаят", "Mary Region"), [C("Mary", "Мары"), C("Bayramaly", "Байрамали")]),
]

RU = [
    (C("Markaziy federal okrug", "Центральный федеральный округ", "Central Federal District"), [
        C("Moskva", "Москва", "Moscow"), C("Voronezh", "Воронеж"), C("Yaroslavl", "Ярославль"), C("Tula", "Тула"), C("Ryazan", "Рязань"), C("Lipetsk", "Липецк"),
        C("Tver", "Тверь"), C("Kursk", "Курск"), C("Belgorod", "Белгород"), C("Bryansk", "Брянск"), C("Ivanovo", "Иваново"), C("Vladimir", "Владимир"),
        C("Kaluga", "Калуга"), C("Smolensk", "Смоленск"), C("Tambov", "Тамбов"), C("Oryol", "Орёл", "Oryol"), C("Kostroma", "Кострома"),
        C("Podolsk", "Подольск"), C("Khimki", "Химки"), C("Balashikha", "Балашиха"), C("Mytishchi", "Мытищи"), C("Lyubertsy", "Люберцы"), C("Korolyov", "Королёв"),
    ]),
    (C("Shimoli-g'arbiy federal okrug", "Северо-Западный федеральный округ", "Northwestern Federal District"), [
        C("Sankt-Peterburg", "Санкт-Петербург", "Saint Petersburg"), C("Kaliningrad", "Калининград"), C("Arkhangelsk", "Архангельск"), C("Murmansk", "Мурманск"),
        C("Vologda", "Вологда"), C("Cherepovets", "Череповец"), C("Petrozavodsk", "Петрозаводск"), C("Pskov", "Псков"), C("Veliky Novgorod", "Великий Новгород"), C("Syktyvkar", "Сыктывкар"),
    ]),
    (C("Janubiy federal okrug", "Южный федеральный округ", "Southern Federal District"), [
        C("Rostov-na-Donu", "Ростов-на-Дону", "Rostov-on-Don"), C("Krasnodar", "Краснодар"), C("Volgograd", "Волгоград"), C("Astrakhan", "Астрахань"),
        C("Sochi", "Сочи"), C("Novorossiysk", "Новороссийск"), C("Taganrog", "Таганрог"), C("Sevastopol", "Севастополь"), C("Simferopol", "Симферополь"), C("Elista", "Элиста"), C("Maykop", "Майкоп"),
    ]),
    (C("Shimoliy Kavkaz federal okrugi", "Северо-Кавказский федеральный округ", "North Caucasian Federal District"), [
        C("Makhachkala", "Махачкала"), C("Stavropol", "Ставрополь"), C("Pyatigorsk", "Пятигорск"), C("Grozny", "Грозный"), C("Vladikavkaz", "Владикавказ"),
        C("Nalchik", "Нальчик"), C("Cherkessk", "Черкесск"), C("Nazran", "Назрань"), C("Derbent", "Дербент"),
    ]),
    (C("Volga bo'yi federal okrugi", "Приволжский федеральный округ", "Volga Federal District"), [
        C("Kazan", "Казань"), C("Nizhny Novgorod", "Нижний Новгород"), C("Samara", "Самара"), C("Ufa", "Уфа"), C("Perm", "Пермь"), C("Saratov", "Саратов"),
        C("Tolyatti", "Тольятти"), C("Izhevsk", "Ижевск"), C("Ulyanovsk", "Ульяновск"), C("Orenburg", "Оренбург"), C("Penza", "Пенза"), C("Kirov", "Киров"),
        C("Cheboksary", "Чебоксары"), C("Saransk", "Саранск"), C("Yoshkar-Ola", "Йошкар-Ола"), C("Naberezhnye Chelny", "Набережные Челны"), C("Sterlitamak", "Стерлитамак"),
    ]),
    (C("Ural federal okrugi", "Уральский федеральный округ", "Ural Federal District"), [
        C("Yekaterinburg", "Екатеринбург"), C("Chelyabinsk", "Челябинск"), C("Tyumen", "Тюмень"), C("Magnitogorsk", "Магнитогорск"), C("Surgut", "Сургут"),
        C("Nizhny Tagil", "Нижний Тагил"), C("Kurgan", "Курган"), C("Nizhnevartovsk", "Нижневартовск"), C("Khanty-Mansiysk", "Ханты-Мансийск"), C("Novy Urengoy", "Новый Уренгой"), C("Salekhard", "Салехард"),
    ]),
    (C("Sibir federal okrugi", "Сибирский федеральный округ", "Siberian Federal District"), [
        C("Novosibirsk", "Новосибирск"), C("Omsk", "Омск"), C("Krasnoyarsk", "Красноярск"), C("Barnaul", "Барнаул"), C("Irkutsk", "Иркутск"), C("Tomsk", "Томск"),
        C("Kemerovo", "Кемерово"), C("Novokuznetsk", "Новокузнецк"), C("Abakan", "Абакан"), C("Kyzyl", "Кызыл"), C("Gorno-Altaysk", "Горно-Алтайск"), C("Bratsk", "Братск"), C("Biysk", "Бийск"),
    ]),
    (C("Uzoq Sharq federal okrugi", "Дальневосточный федеральный округ", "Far Eastern Federal District"), [
        C("Vladivostok", "Владивосток"), C("Khabarovsk", "Хабаровск"), C("Ulan-Ude", "Улан-Удэ"), C("Chita", "Чита"), C("Yakutsk", "Якутск"),
        C("Blagoveshchensk", "Благовещенск"), C("Yuzhno-Sakhalinsk", "Южно-Сахалинск"), C("Petropavlovsk-Kamchatsky", "Петропавловск-Камчатский"), C("Magadan", "Магадан"), C("Birobidzhan", "Биробиджан"), C("Anadyr", "Анадырь"),
    ]),
]

CN = [
    (C("Guangdong", "Гуандун", "Guangdong"), [C("Guangzhou", "Гуанчжоу"), C("Shenzhen", "Шэньчжэнь"), C("Dongguan", "Дунгуань"), C("Foshan", "Фошань"), C("Zhuhai", "Чжухай")]),
    (C("Zhejiang", "Чжэцзян", "Zhejiang"), [C("Yiwu", "Иу"), C("Hangzhou", "Ханчжоу"), C("Ningbo", "Нинбо"), C("Wenzhou", "Вэньчжоу")]),
    (C("Xinjiang", "Синьцзян", "Xinjiang"), [C("Urumqi", "Урумчи"), C("Kashgar", "Кашгар"), C("Khorgos", "Хоргос"), C("Yining", "Инин")]),
    (C("Boshqa shaharlar", "Другие города", "Other cities"), [C("Beijing", "Пекин"), C("Shanghai", "Шанхай"), C("Chengdu", "Чэнду"), C("Xi'an", "Сиань"), C("Tianjin", "Тяньцзинь"), C("Qingdao", "Циндао"), C("Hong Kong", "Гонконг")]),
]

AZ = [(None, [C("Baku", "Баку"), C("Ganja", "Гянджа"), C("Sumgait", "Сумгаит"), C("Mingachevir", "Мингечевир"), C("Lankaran", "Ленкорань"), C("Nakhchivan", "Нахичевань"), C("Shaki", "Шеки")])]
GE = [(None, [C("Tbilisi", "Тбилиси"), C("Batumi", "Батуми"), C("Kutaisi", "Кутаиси"), C("Rustavi", "Рустави"), C("Gori", "Гори"), C("Zugdidi", "Зугдиди"), C("Poti", "Поти")])]
AM = [(None, [C("Yerevan", "Ереван"), C("Gyumri", "Гюмри"), C("Vanadzor", "Ванадзор"), C("Vagharshapat", "Вагаршапат"), C("Hrazdan", "Раздан"), C("Abovyan", "Абовян")])]
TR = [(None, [C("Istanbul", "Стамбул"), C("Ankara", "Анкара"), C("Izmir", "Измир"), C("Bursa", "Бурса"), C("Antalya", "Анталья"), C("Adana", "Адана"), C("Konya", "Конья"), C("Gaziantep", "Газиантеп"), C("Mersin", "Мерсин"), C("Trabzon", "Трабзон")])]
AF = [(None, [C("Kabul", "Кабул"), C("Mazar-i-Sharif", "Мазари-Шариф"), C("Herat", "Герат"), C("Kandahar", "Кандагар"), C("Kunduz", "Кундуз"), C("Jalalabad", "Джелалабад"), C("Sheberghan", "Шибирган"), C("Hairatan", "Хайратон")])]
MN = [(None, [C("Ulaanbaatar", "Улан-Батор"), C("Erdenet", "Эрдэнэт"), C("Darkhan", "Дархан"), C("Choibalsan", "Чойбалсан")])]
BY = [(None, [C("Minsk", "Минск"), C("Gomel", "Гомель"), C("Mogilev", "Могилёв"), C("Vitebsk", "Витебск"), C("Grodno", "Гродно"), C("Brest", "Брест")])]
PK = [(None, [C("Karachi", "Карачи"), C("Lahore", "Лахор"), C("Islamabad", "Исламабад"), C("Rawalpindi", "Равалпинди"), C("Peshawar", "Пешавар"), C("Faisalabad", "Фейсалабад")])]
IR = [(None, [C("Tehran", "Тегеран"), C("Mashhad", "Мешхед"), C("Isfahan", "Исфахан"), C("Tabriz", "Тебриз"), C("Shiraz", "Шираз"), C("Bandar Abbas", "Бендер-Аббас")])]
AE = [(None, [C("Dubai", "Дубай"), C("Abu Dhabi", "Абу-Даби"), C("Sharjah", "Шарджа"), C("Ajman", "Аджман")])]
KR = [(None, [C("Seoul", "Сеул"), C("Busan", "Пусан"), C("Incheon", "Инчхон"), C("Daegu", "Тэгу")])]

COUNTRIES = [
    # code, flag, phone, names, regions   (order = display order)
    ("UZ", "🇺🇿", "+998", {"uz": "Ўзбекистон", "uzl": "O'zbekiston", "ru": "Узбекистан", "en": "Uzbekistan", "zh": "乌兹别克斯坦"}, UZ),
    ("KZ", "🇰🇿", "+7", {"uz": "Қозоғистон", "uzl": "Qozog'iston", "ru": "Казахстан", "en": "Kazakhstan", "zh": "哈萨克斯坦"}, KZ),
    ("KG", "🇰🇬", "+996", {"uz": "Қирғизистон", "uzl": "Qirg'iziston", "ru": "Кыргызстан", "en": "Kyrgyzstan", "zh": "吉尔吉斯斯坦"}, KG),
    ("TJ", "🇹🇯", "+992", {"uz": "Тожикистон", "uzl": "Tojikiston", "ru": "Таджикистан", "en": "Tajikistan", "zh": "塔吉克斯坦"}, TJ),
    ("TM", "🇹🇲", "+993", {"uz": "Туркманистон", "uzl": "Turkmaniston", "ru": "Туркменистан", "en": "Turkmenistan", "zh": "土库曼斯坦"}, TM),
    ("RU", "🇷🇺", "+7", {"uz": "Россия", "uzl": "Rossiya", "ru": "Россия", "en": "Russia", "zh": "俄罗斯"}, RU),
    ("CN", "🇨🇳", "+86", {"uz": "Хитой", "uzl": "Xitoy", "ru": "Китай", "en": "China", "zh": "中国"}, CN),
    ("AZ", "🇦🇿", "+994", {"uz": "Озарбайжон", "uzl": "Ozarbayjon", "ru": "Азербайджан", "en": "Azerbaijan", "zh": "阿塞拜疆"}, AZ),
    ("GE", "🇬🇪", "+995", {"uz": "Грузия", "uzl": "Gruziya", "ru": "Грузия", "en": "Georgia", "zh": "格鲁吉亚"}, GE),
    ("AM", "🇦🇲", "+374", {"uz": "Арманистон", "uzl": "Armaniston", "ru": "Армения", "en": "Armenia", "zh": "亚美尼亚"}, AM),
    ("TR", "🇹🇷", "+90", {"uz": "Туркия", "uzl": "Turkiya", "ru": "Турция", "en": "Türkiye", "zh": "土耳其"}, TR),
    ("AF", "🇦🇫", "+93", {"uz": "Афғонистон", "uzl": "Afg'oniston", "ru": "Афганистан", "en": "Afghanistan", "zh": "阿富汗"}, AF),
    ("MN", "🇲🇳", "+976", {"uz": "Мўғулистон", "uzl": "Mo'g'uliston", "ru": "Монголия", "en": "Mongolia", "zh": "蒙古"}, MN),
    ("BY", "🇧🇾", "+375", {"uz": "Беларусь", "uzl": "Belarus", "ru": "Беларусь", "en": "Belarus", "zh": "白俄罗斯"}, BY),
    ("PK", "🇵🇰", "+92", {"uz": "Покистон", "uzl": "Pokiston", "ru": "Пакистан", "en": "Pakistan", "zh": "巴基斯坦"}, PK),
    ("IR", "🇮🇷", "+98", {"uz": "Эрон", "uzl": "Eron", "ru": "Иран", "en": "Iran", "zh": "伊朗"}, IR),
    ("AE", "🇦🇪", "+971", {"uz": "БАА", "uzl": "BAA", "ru": "ОАЭ", "en": "United Arab Emirates", "zh": "阿联酋"}, AE),
    ("KR", "🇰🇷", "+82", {"uz": "Жанубий Корея", "uzl": "Janubiy Koreya", "ru": "Южная Корея", "en": "South Korea", "zh": "韩国"}, KR),
    ("OT", "🌍", "", {"uz": "Бошқа", "uzl": "Boshqa", "ru": "Другая", "en": "Other", "zh": "其他"}, []),
]

# Latin (1995) → Cyrillic for Uzbek place names. Digraphs first, then single letters; keeps case.
_DIGRAPHS = [("yo'", "йў"), ("yo‘", "йў"), ("yoʻ", "йў"), ("o'", "ў"), ("o‘", "ў"), ("oʻ", "ў"), ("g'", "ғ"), ("g‘", "ғ"), ("gʻ", "ғ"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ye", "е"), ("ts", "ц")]
_SINGLE = dict(zip("abdefghijklmnopqrstuvxyz'", "абдефгҳижклмнопқрстувхйзъ", strict=True))


def latin_to_cyrillic(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        matched = False
        for lat, cyr in _DIGRAPHS:
            L = len(lat)
            seg = text[i:i + L]
            if seg.lower() == lat:
                c = cyr.upper() if seg[0].isupper() else cyr
                out.append(c)
                i += L
                matched = True
                break
        if matched:
            continue
        low = ch.lower()
        if low == "e":
            prev = text[i - 1].lower() if i > 0 else " "
            c = "э" if (not prev.isalpha() or prev in "aeiou'") else "е"
        elif low == "c":
            c = "с"
        elif low == "w":
            c = "в"
        else:
            c = _SINGLE.get(low, ch)
        out.append(c.upper() if ch.isupper() and c != ch else c)
        i += 1
    return "".join(out)


def names_for(country_code: str, latin: str, ru: str, en: str) -> dict:
    """Build the i18n dict for a region/city. Uzbek Cyrillic: transliterated for UZ, Russian spelling elsewhere."""
    uz = latin_to_cyrillic(latin) if country_code == "UZ" else ru
    return {"uz": uz, "uzl": latin, "ru": ru, "en": en}


def iter_places(country_code: str, regions):
    """Yield (region_names | None, city_names) for a country entry."""
    for region, cities in regions:
        rn = names_for(country_code, *region) if region else None
        for city in cities:
            yield rn, names_for(country_code, *city)
