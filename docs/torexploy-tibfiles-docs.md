# Integratsiya hujjatlari — TibFiles

Fayl omborini ilovangizga ulash: parametrlar, SDK namunalari, havolalar, kalitlar va cheklovlar — hammasi aynan shu ombor uchun toʻldirilgan.

_29-okt, 2026, 22:08 · http://169.58.230.136:2003/services/svc_ghddwjwhj8xfwn/docs_

> Maxfiy kalit (secret) hech qachon koʻrsatilmaydi: namunalardagi `<SECRET_ACCESS_KEY>` oʻrniga kalit yaratilganda bir marta koʻrsatilgan qiymatni qoʻying. Asosiy kalitning secret’i Umumiy tabida «Koʻrsatish» orqali olinadi.

## Tezkor boshlash

1. **Bucket yarating** — Fayllar tabida: masalan `uploads` (yopiq) yoki `public` (ochiq — fayllar kalitsiz oʻqiladi). Nom 3–63 ta kichik harf, raqam, nuqta yoki chiziqcha.
2. **Ilova uchun kalit yarating** — Kalitlar tabida: nom, huquq (faqat oʻqish / oʻqish va yozish) va qaysi bucket’lar. Secret faqat bir marta koʻrsatiladi — darhol saqlang.
3. **Ulang** — TorexPloy’dagi ilova boʻlsa — ilovaning Oʻzgaruvchilar tabida **Ulanish qoʻshish** (oʻzgaruvchilar avtomatik keladi). Tashqi ilova boʻlsa — quyidagi SDK namunasini oling va tashqi manzil (domen) bilan ulaning.
4. **Tekshiring** — Fayl yuklang va Fayllar tabida koʻring. Xato boʻlsa — «Muammolar» boʻlimi.

## Ulanish parametrlari

Istalgan S3 klienti uchun toʻrtta narsa kerak: endpoint, region, path-style va kalit juftligi. Bucket nomi manzilning **yoʻl** qismida boʻladi (`endpoint/bucket/kalit`), subdomen emas.

|  |  |
| --- | --- |
| Tashqi endpoint | `http://tibfiles-ghddwj.169-58-230-136.sslip.io` |
| Ichki endpoint | `http://tibfiles:8333` — faqat shu loyihadagi ilovalardan (konteyner tarmogʻi orqali), TLS’siz |
| Region | `us-east-1` |
| Manzil uslubi (path-style) | `http://tibfiles-ghddwj.169-58-230-136.sslip.io/backups/<key>` |
| Access key ID | `ployf9b99909pt0b` |
| Secret access key | Kalit yaratilganda bir marta koʻrsatiladi; asosiy kalitniki — Umumiy tabida «Koʻrsatish». |

## TorexPloy ilovasini ulash

Shu loyihadagi ilova omborga **ulanish** orqali bogʻlanadi: parollar nusxalanmaydi, oʻzgaruvchilar keyingi joylashtirishda beriladi va ombor sozlamalari oʻzgarsa, ulanish ham yangilanadi.

1. **Ilova → Oʻzgaruvchilar → Ulanish qoʻshish** — Omborni va prefiksni tanlang (standart `S3_`). Prefiks oʻzgaruvchi nomlarining boshiga qoʻshiladi.
2. **Joylashtiring** — Oʻzgaruvchilar keyingi deploy’dan boshlab konteynerga beriladi («Hozir joylashtirish» eslatmasi chiqadi).
3. **Kodda oʻqing** — Endpoint, kalit va regionni kodga yozmang — faqat oʻzgaruvchilardan oling (quyidagi namuna).

Prefiks: `S3_`

| Oʻzgaruvchi | Qiymat | Izoh |
| --- | --- | --- |
| `S3_S3_ENDPOINT` | `http://tibfiles:8333` | Ichki manzil — loyiha tarmogʻi ichida ishlaydi. |
| `S3_S3_ACCESS_KEY_ID` | `ployf9b99909pt0b` | Asosiy (root) kalit. |
| `S3_S3_SECRET_ACCESS_KEY` | `••••••••` | Maxfiy; konteynerga shifrsiz beriladi. |
| `S3_S3_REGION` | `us-east-1` | Istalgan qiymat qabul qilinadi; SDK’lar uchun shu kerak. |
| `S3_S3_FORCE_PATH_STYLE` | `true` | Doim `true`. |
| `S3_S3_BUCKET` | — | Boʻsh: oʻzingiz toʻldiring yoki kodda belgilang. |
| `S3_AWS_ENDPOINT_URL` | `http://tibfiles:8333` | AWS SDK’lar avtomatik oʻqiydigan standart nomlar. |
| `S3_AWS_ACCESS_KEY_ID` | `ployf9b99909pt0b` | AWS SDK’lar avtomatik oʻqiydigan standart nomlar. |
| `S3_AWS_SECRET_ACCESS_KEY` | `••••••••` | AWS SDK’lar avtomatik oʻqiydigan standart nomlar. |
| `S3_AWS_REGION` | `us-east-1` | AWS SDK’lar avtomatik oʻqiydigan standart nomlar. |

> Ulanish asosiy (root) kalitni beradi — u barcha bucket’larga toʻliq huquqli. Ilova faqat oʻz bucket’iga kirishi kerak boʻlsa, Kalitlar tabida cheklangan kalit yarating va uni ilovaning oʻz oʻzgaruvchisi sifatida qoʻying.

```ts
// The linked app reads its variables; nothing is hard-coded.
import { S3Client } from '@aws-sdk/client-s3';

const s3 = new S3Client({
  endpoint: process.env.S3_S3_ENDPOINT,
  region: process.env.S3_S3_REGION,
  forcePathStyle: process.env.S3_S3_FORCE_PATH_STYLE === 'true',
  credentials: { accessKeyId: process.env.S3_S3_ACCESS_KEY_ID!, secretAccessKey: process.env.S3_S3_SECRET_ACCESS_KEY! },
});

# Python
s3 = boto3.client('s3', endpoint_url=os.environ['S3_S3_ENDPOINT'], aws_access_key_id=os.environ['S3_S3_ACCESS_KEY_ID'],
                  aws_secret_access_key=os.environ['S3_S3_SECRET_ACCESS_KEY'], region_name=os.environ['S3_S3_REGION'],
                  config=Config(s3={'addressing_style': 'path'}))
```

## SDK va vositalar

Har bir namunada endpoint, region, bucket va tanlangan kalit toʻldirilgan. Uchta qoida hamma uchun bir xil: **endpoint** ni koʻrsating, **path-style** ni yoqing, **region** ni bering (`us-east-1` yetarli).

### Node.js

```ts
// npm i @aws-sdk/client-s3 @aws-sdk/s3-request-presigner
import { S3Client, PutObjectCommand, GetObjectCommand, ListObjectsV2Command } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

const s3 = new S3Client({
  endpoint: process.env.S3_ENDPOINT ?? 'http://tibfiles-ghddwj.169-58-230-136.sslip.io',
  region: process.env.S3_REGION ?? 'us-east-1',
  forcePathStyle: true, // required: endpoint/bucket/key
  credentials: { accessKeyId: process.env.S3_ACCESS_KEY_ID ?? 'ployf9b99909pt0b', secretAccessKey: process.env.S3_SECRET_ACCESS_KEY ?? '<SECRET_ACCESS_KEY>' },
});
const Bucket = 'backups';

// upload
await s3.send(new PutObjectCommand({ Bucket, Key: 'avatars/u1.png', Body: buffer, ContentType: 'image/png' }));
// list
const { Contents } = await s3.send(new ListObjectsV2Command({ Bucket, Prefix: 'avatars/' }));
// temporary download link (1 hour) for a private bucket
const url = await getSignedUrl(s3, new GetObjectCommand({ Bucket, Key: 'avatars/u1.png' }), { expiresIn: 3600 });
// temporary upload link: the browser PUTs the file straight into the store
const uploadUrl = await getSignedUrl(s3, new PutObjectCommand({ Bucket, Key: 'uploads/doc.pdf', ContentType: 'application/pdf' }), { expiresIn: 600 });
```

### Python

```python
# pip install boto3
import os, boto3
from botocore.config import Config

s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('S3_ENDPOINT', 'http://tibfiles-ghddwj.169-58-230-136.sslip.io'),
    aws_access_key_id=os.getenv('S3_ACCESS_KEY_ID', 'ployf9b99909pt0b'),
    aws_secret_access_key=os.getenv('S3_SECRET_ACCESS_KEY', '<SECRET_ACCESS_KEY>'),
    region_name='us-east-1',
    config=Config(s3={'addressing_style': 'path'}, signature_version='s3v4'),
)
BUCKET = 'backups'

s3.upload_file('report.pdf', BUCKET, 'reports/2026-10.pdf', ExtraArgs={'ContentType': 'application/pdf'})
s3.download_file(BUCKET, 'reports/2026-10.pdf', '/tmp/report.pdf')
for obj in s3.list_objects_v2(Bucket=BUCKET, Prefix='reports/').get('Contents', []):
    print(obj['Key'], obj['Size'])
# temporary link (1 hour)
url = s3.generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': 'reports/2026-10.pdf'}, ExpiresIn=3600)
```

### PHP / Laravel

```php
// composer require league/flysystem-aws-s3-v3   (Laravel 9+)
// .env
AWS_ACCESS_KEY_ID=ployf9b99909pt0b
AWS_SECRET_ACCESS_KEY=<SECRET_ACCESS_KEY>
AWS_DEFAULT_REGION=us-east-1
AWS_BUCKET=backups
AWS_ENDPOINT=http://tibfiles-ghddwj.169-58-230-136.sslip.io
AWS_USE_PATH_STYLE_ENDPOINT=true

// config/filesystems.php already reads these for the 's3' disk.
Storage::disk('s3')->put('avatars/u1.png', $contents, 'public');
$url = Storage::disk('s3')->temporaryUrl('invoices/42.pdf', now()->addHour()); // private bucket
$public = Storage::disk('s3')->url('avatars/u1.png');                        // public bucket

// Plain PHP (aws/aws-sdk-php):
$s3 = new Aws\S3\S3Client(['version' => 'latest', 'region' => 'us-east-1', 'endpoint' => 'http://tibfiles-ghddwj.169-58-230-136.sslip.io',
  'use_path_style_endpoint' => true, 'credentials' => ['key' => 'ployf9b99909pt0b', 'secret' => '<SECRET_ACCESS_KEY>']]);
$s3->putObject(['Bucket' => 'backups', 'Key' => 'avatars/u1.png', 'Body' => $contents, 'ContentType' => 'image/png']);
```

### Go

```go
// go get github.com/aws/aws-sdk-go-v2/{config,credentials,service/s3}
cfg, err := config.LoadDefaultConfig(ctx,
    config.WithRegion("us-east-1"),
    config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("ployf9b99909pt0b", "<SECRET_ACCESS_KEY>", "")),
)
client := s3.NewFromConfig(cfg, func(o *s3.Options) {
    o.BaseEndpoint = aws.String("http://tibfiles-ghddwj.169-58-230-136.sslip.io")
    o.UsePathStyle = true
})

_, err = client.PutObject(ctx, &s3.PutObjectInput{Bucket: aws.String("backups"), Key: aws.String("avatars/u1.png"), Body: file, ContentType: aws.String("image/png")})

// temporary link (1 hour)
presigner := s3.NewPresignClient(client)
req, err := presigner.PresignGetObject(ctx, &s3.GetObjectInput{Bucket: aws.String("backups"), Key: aws.String("avatars/u1.png")}, s3.WithPresignExpires(time.Hour))
fmt.Println(req.URL)
```

### Java

```java
// software.amazon.awssdk:s3 (AWS SDK v2)
S3Client s3 = S3Client.builder()
    .endpointOverride(URI.create("http://tibfiles-ghddwj.169-58-230-136.sslip.io"))
    .region(Region.of("us-east-1"))
    .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("ployf9b99909pt0b", "<SECRET_ACCESS_KEY>")))
    .forcePathStyle(true)
    .build();

s3.putObject(PutObjectRequest.builder().bucket("backups").key("avatars/u1.png").contentType("image/png").build(), RequestBody.fromFile(path));

// temporary link (1 hour)
S3Presigner presigner = S3Presigner.builder()
    .endpointOverride(URI.create("http://tibfiles-ghddwj.169-58-230-136.sslip.io")).region(Region.of("us-east-1"))
    .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("ployf9b99909pt0b", "<SECRET_ACCESS_KEY>")))
    .serviceConfiguration(S3Configuration.builder().pathStyleAccessEnabled(true).build()).build();
String url = presigner.presignGetObject(GetObjectPresignRequest.builder().signatureDuration(Duration.ofHours(1))
    .getObjectRequest(GetObjectRequest.builder().bucket("backups").key("avatars/u1.png").build()).build()).url().toString();
```

### .NET

```csharp
// dotnet add package AWSSDK.S3
var config = new AmazonS3Config {
    ServiceURL = "http://tibfiles-ghddwj.169-58-230-136.sslip.io",
    ForcePathStyle = true,
    AuthenticationRegion = "us-east-1",
};
var s3 = new AmazonS3Client("ployf9b99909pt0b", "<SECRET_ACCESS_KEY>", config);

await s3.PutObjectAsync(new PutObjectRequest { BucketName = "backups", Key = "avatars/u1.png", FilePath = path, ContentType = "image/png" });

// temporary link (1 hour)
var url = s3.GetPreSignedURL(new GetPreSignedUrlRequest { BucketName = "backups", Key = "avatars/u1.png", Expires = DateTime.UtcNow.AddHours(1) });
```

### Ruby

```ruby
# gem 'aws-sdk-s3'
require "aws-sdk-s3"

client = Aws::S3::Client.new(
  endpoint: "http://tibfiles-ghddwj.169-58-230-136.sslip.io",
  region: "us-east-1",
  access_key_id: "ployf9b99909pt0b",
  secret_access_key: "<SECRET_ACCESS_KEY>",
  force_path_style: true,
)
bucket = Aws::S3::Resource.new(client: client).bucket("backups")

bucket.object("avatars/u1.png").upload_file("u1.png", content_type: "image/png")
url = bucket.object("invoices/42.pdf").presigned_url(:get, expires_in: 3600) # temporary link

# Rails Active Storage (config/storage.yml):
# torexploy:
#   service: S3
#   endpoint: http://tibfiles-ghddwj.169-58-230-136.sslip.io
#   region: us-east-1
#   bucket: backups
#   force_path_style: true
#   access_key_id: <%= ENV["S3_ACCESS_KEY_ID"] %>
#   secret_access_key: <%= ENV["S3_SECRET_ACCESS_KEY"] %>
```

### Django

```python
# pip install django-storages boto3
# settings.py
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "endpoint_url": "http://tibfiles-ghddwj.169-58-230-136.sslip.io",
            "region_name": "us-east-1",
            "bucket_name": "backups",
            "access_key": "ployf9b99909pt0b",
            "secret_key": "<SECRET_ACCESS_KEY>",
            "addressing_style": "path",
            "signature_version": "s3v4",
            "querystring_auth": True,   # private bucket: temporary links
            "default_acl": None,
        },
    },
}

# models.py
class Document(models.Model):
    file = models.FileField(upload_to="documents/")

# doc.file.url -> temporary link (private bucket) or direct link (public bucket)
```

### AWS CLI

```bash
# pip install awscli  (or the official installer)
aws configure set aws_access_key_id ployf9b99909pt0b
aws configure set aws_secret_access_key <SECRET_ACCESS_KEY>
aws configure set region us-east-1

aws --endpoint-url http://tibfiles-ghddwj.169-58-230-136.sslip.io s3 ls
aws --endpoint-url http://tibfiles-ghddwj.169-58-230-136.sslip.io s3 cp ./photo.png s3://backups/photos/photo.png
aws --endpoint-url http://tibfiles-ghddwj.169-58-230-136.sslip.io s3 sync ./public s3://backups/site --delete
aws --endpoint-url http://tibfiles-ghddwj.169-58-230-136.sslip.io s3 presign s3://backups/photos/photo.png --expires-in 3600
```

### rclone

```bash
rclone config create torexploy s3 provider=Other endpoint=http://tibfiles-ghddwj.169-58-230-136.sslip.io access_key_id=ployf9b99909pt0b secret_access_key=<SECRET_ACCESS_KEY> region=us-east-1 force_path_style=true

rclone lsd torexploy:
rclone copy ./photos torexploy:backups/photos --progress
rclone sync ./backups torexploy:backups/backups --progress
rclone mount torexploy:backups /mnt/files --vfs-cache-mode writes   # mount as a folder
```

### s3cmd

```bash
s3cmd --configure   # answer: Access Key ployf9b99909pt0b, Secret <SECRET_ACCESS_KEY>, S3 Endpoint tibfiles-ghddwj.169-58-230-136.sslip.io
# or put these in ~/.s3cfg:
host_base = tibfiles-ghddwj.169-58-230-136.sslip.io
host_bucket = tibfiles-ghddwj.169-58-230-136.sslip.io
use_https = False
access_key = ployf9b99909pt0b
secret_key = <SECRET_ACCESS_KEY>

s3cmd ls s3://backups/
s3cmd put ./photo.png s3://backups/photos/photo.png
```

### MinIO mc

```bash
mc alias set torexploy http://tibfiles-ghddwj.169-58-230-136.sslip.io ployf9b99909pt0b <SECRET_ACCESS_KEY> --api S3v4 --path on

mc ls torexploy/backups
mc cp ./photo.png torexploy/backups/photos/photo.png
mc mirror ./public torexploy/backups/site
mc share download torexploy/backups/photos/photo.png --expire 1h
```

- Fayl turini (`Content-Type`) yuklashda bering — aks holda brauzer uni yuklab olish sifatida ochadi.
- Katta fayllar: SDK’lar multipart yuklashni oʻzi qiladi (Node — `@aws-sdk/lib-storage` `Upload`, Python — `upload_file`).
- Papka tushunchasi yoʻq: `photos/2026/a.png` kabi kalitdagi `/` papka kabi koʻrinadi.

## Ochiq fayllar va vaqtinchalik havolalar

**Ochiq bucket** (Fayllar tabida «Ochiq qilish»): har bir fayl kalitsiz, toʻgʻridan-toʻgʻri havola orqali ochiladi — saytdagi rasmlar, avatarlar, statik fayllar uchun. Format:

```
http://tibfiles-ghddwj.169-58-230-136.sslip.io/backups/photos/photo.png
```

**Yopiq bucket**: fayl faqat kalit bilan yoki **vaqtinchalik (presigned) havola** orqali ochiladi. Havola SDK’da yoki panel API’da yaratiladi (60 soniyadan 7 kungacha) — hisob-fakturalar, shaxsiy hujjatlar uchun.

- Vaqtinchalik havola uni yaratgan kalit bekor qilinsa ishlamay qoladi.
- Ochiq bucket’ga **yozish** baribir kalit talab qiladi; ochiqlik faqat oʻqishga tegishli.
- Domen qoʻshilgan boʻlsa havolalar HTTPS; ichki manzil bilan yaratilgan havola tashqaridan ochilmaydi.

## Brauzerdan toʻgʻridan-toʻgʻri yuklash

Katta fayllarni serveringiz orqali oʻtkazmang: server **vaqtinchalik PUT havola** beradi, brauzer faylni toʻgʻridan-toʻgʻri omborga yuboradi, soʻng kalitni bazangizga yozasiz.

```ts
// 1) Server: issue a temporary upload link (any SDK above does this with a PutObject presign)
app.post('/api/upload-url', async (req, res) => {
  const Key = `uploads/${crypto.randomUUID()}-${req.body.name}`;
  const url = await getSignedUrl(s3, new PutObjectCommand({ Bucket, Key, ContentType: req.body.type }), { expiresIn: 600 });
  res.json({ url, key: Key });
});

// 2) Browser: send the file straight to the store, bypassing your server
const { url, key } = await fetch('/api/upload-url', { method: 'POST', body: JSON.stringify({ name: file.name, type: file.type }), headers: { 'content-type': 'application/json' } }).then((r) => r.json());
await fetch(url, { method: 'PUT', body: file, headers: { 'content-type': file.type } });
// 3) Save `key` in your database; serve it later with a GET presign (private) or a direct link (public bucket).
```

> Brauzer konsolida CORS xatosi chiqsa, S3 shlyuz brauzer soʻrovlarini rad etgan boʻladi — bunday holda yuklashni oʻz serveringiz orqali (SDK bilan) oʻtkazing yoki ombor oldiga oʻz proksingizni qoʻying.

## Kalitlar va huquqlar

- **Faqat oʻqish** — fayllarni oʻqish va roʻyxatini olish; **Oʻqish va yozish** — qoʻshimcha yuklash va oʻchirish.
- **Bucket’lar** — «Barcha» (keyin yaratiladiganlar ham) yoki faqat tanlanganlar. Ilova faqat oʻz bucket’ini koʻrishi kerak.
- Kalitlar **bucket yarata olmaydi** — bucket faqat panelda (yoki panel API orqali) yaratiladi.
- «Oxirgi foydalanish» ustuni kalit haqiqatan ishlatilayotganini koʻrsatadi.
- Zaxira nusxalar uchun panel oʻzi `backups` kalitini yaratadi — uni tahrirlab boʻlmaydi, faqat manzil bilan birga bekor qilinadi.

> **Kalitni almashtirish** — Yangi kalit yarating → ilovani yangi kalitga oʻtkazing va joylashtiring → eski kalitni bekor qiling. Bekor qilingan kalit darhol ishlamay qoladi.

## Zaxira nusxalar

Umumiy tabida «Zaxira manzili sifatida yoqish» bosilsa, `backups` bucket’i va alohida kalit yaratilib, ombor **S3 manzillar** roʻyxatiga qoʻshiladi. Shundan keyin istalgan bazaning Zaxira nusxalar tabida shu omborni tanlash mumkin — har bir nusxa shu yerga ham yoziladi.

## Cheklovlar va eslatmalar

- Faqat **path-style** manzil ishlaydi (`endpoint/bucket/kalit`); virtual-host uslubi (`bucket.endpoint`) qoʻllab-quvvatlanmaydi.
- Region tekshirilmaydi, lekin SDK’lar talab qiladi — `us-east-1` bering.
- Panel orqali bitta yuklashda **5 GB** gacha; SDK orqali chegara yoʻq (multipart).
- Versiyalash (versioning), lifecycle qoidalari va bucket siyosatlari (bucket policy) yoʻq — huquqlar kalitlar orqali boshqariladi.
- Ichki endpoint HTTP (loyiha tarmogʻi ichida), tashqi endpoint domen bilan HTTPS.
- Bucket’ni oʻchirish uchun u boʻsh boʻlishi kerak yoki «barcha fayllar bilan» tasdiqlanadi.
- Ombor bitta konteynerda (SeaweedFS): maʼlumotlar servis diskida; servis oʻchirilganda disk saqlanishini tanlash mumkin.

## Muammolar

**`SignatureDoesNotMatch` yoki `403` har bir soʻrovda**

Koʻpincha path-style yoqilmagan yoki secret notoʻgʻri nusxalangan (boʻsh joy). Signature v4 ishlating; region `us-east-1`; endpoint’da bucket nomi boʻlmasin.

**`AccessDenied`**

Kalit shu bucket’ga ruxsatsiz yoki «faqat oʻqish» huquqida. Kalitlar tabida bucket’lar roʻyxatini va huquqni tekshiring; bucket yaratish kalitlarga umuman mumkin emas.

**`NoSuchBucket`**

Bucket nomi notoʻgʻri yoki hali yaratilmagan — Fayllar tabida yarating. Virtual-host uslubida (`bucket.endpoint`) ham shu xato chiqadi: path-style’ga oʻting.

**`ECONNREFUSED` / timeout**

Ichki manzil (`http://<nom>:8333`) faqat shu loyihadagi ilovalardan ishlaydi. Tashqaridan — Domenlar tabida domen qoʻshing (HTTPS) yoki tashqi portni oching va firewall’da ruxsat bering.

**Ochiq havola `403` beradi**

Bucket ochiq emas — Fayllar tabida «Ochiq qilish». Yoki havola ichki manzil bilan tuzilgan.

**Brauzer rasmni koʻrsatmay, yuklab oladi**

Yuklashda `Content-Type` berilmagan (`application/octet-stream`). Faylni toʻgʻri tur bilan qayta yuklang.

**Vaqtinchalik havola muddati tugamay ishlamay qoldi**

Havolani yaratgan kalit bekor qilingan yoki soat farqi katta (SigV4 15 daqiqa farqga chidaydi) — server vaqtini tekshiring.

## Panel API orqali boshqarish

CI yoki skriptlar bucket, kalit va fayllarni panel API orqali boshqarishi mumkin — S3 kalitisiz, faqat **API token** bilan. Tokenlar jamoaga bogʻliq; `developer` roli yetarli.

```bash
# Create an API token: Settings → API tokens. Send it as a Bearer token.
TOKEN=ploy_…
BASE=http://169.58.230.136:2003/api/services/svc_ghddwjwhj8xfwn/storage

# buckets and keys
curl -H "Authorization: Bearer $TOKEN" $BASE/buckets
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -X POST $BASE/buckets -d '{"name":"backups","public":false}'
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -X POST $BASE/keys -d '{"name":"ci-uploader","buckets":["backups"],"permission":"readwrite"}'

# objects: upload, list, temporary link, delete
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: image/png" -X PUT --data-binary @photo.png "$BASE/buckets/backups/objects/photos/photo.png"
curl -H "Authorization: Bearer $TOKEN" "$BASE/buckets/backups/objects?prefix=photos/"
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -X POST "$BASE/buckets/backups/presign" -d '{"key":"photos/photo.png","method":"get","expiresIn":3600}'
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -X POST "$BASE/buckets/backups/delete" -d '{"keys":["photos/photo.png"]}'
```

- Fayl yuklash: `PUT …/objects/<kalit>` — xom body, `Content-Type` va `Content-Length` majburiy.
- Roʻyxat sahifalanadi: javobdagi `nextCursor` ni `?cursor=` bilan qaytaring.
- Vaqtinchalik havola: `POST …/presign` — `method: "get" | "put"`, `expiresIn` 60–604800 soniya.
- Barcha amallar audit jurnaliga yoziladi.
