# AI Фото/Видео Редактор — MAX Bot

## Что это

MAX-версия рабочего Telegram-бота из `telegram_video_bot`.

Назначение сохранено:
- генерация видео из фото по готовым эффектам;
- генерация видео из фото по своему промпту;
- обработка фото по готовым фото-идеям;
- ИИ-Фотошоп по своему промпту;
- генерация изображения из текста;
- склейка и обрезка видео через FFmpeg;
- баланс, токены, подписки и автопродление через ЮKassa;
- deeplink-атрибуция `ref_`, `promo_`, UTM;
- админ-команды, промокоды, статистика, smart-рассылка.

`telegram_video_bot` оставлен как неизменяемый источник. Рабочий MAX-проект находится в корне.

## Структура

```text
main.py
config.py
requirements.txt
database/
services/
max_handlers/
max_keyboards/
tools/
media/temp/
media/demos/
telegram_video_bot/       # исходная Telegram-копия, не трогать без причины
```

## MAX-перенос

Транспортный слой заменен:
- `aiogram` больше не используется в корневом проекте;
- входящие сообщения и callbacks идут через `maxapi`;
- FSM реализован простым in-memory state store в `max_handlers/state.py`;
- inline-кнопки собираются через `maxapi` `CallbackButton`/`LinkButton`;
- старые сервисы генерации используют `services/max_adapter.py`, который дает совместимые методы `send_message`, `send_photo`, `send_video`, `download`.
- demo-файлы, добавленные через MAX-админку, сохраняются в `MEDIA_DEMO_DIR`, а не в виде временного URL.
- polling-диспетчер запускается с `use_create_task=True`, чтобы долгая генерация не блокировала кнопки и команды;
- пагинация эффектов пытается обновлять старое сообщение через callback-ответ MAX, с fallback на отправку нового сообщения.

Telegram Stars в MAX напрямую недоступны. Для сохранения разовой покупки добавлена разовая оплата через ЮKassa без `save_payment_method`.

## Переменные окружения

См. `.env.example`.

Главные переменные:
- `MAX_BOT_TOKEN`
- `MAX_USE_WEBHOOK`
- `MAX_WEBHOOK_URL`
- `MAX_WEBHOOK_SECRET`
- `DATABASE_PATH`
- `MEDIA_TEMP_DIR`
- `MEDIA_DEMO_DIR`
- `OFFER_URL`
- `PRODUCT_SUPPORT`
- `YOOKASSA_*`
- `KIE_*`
- `REPLICATE_*`
- `ADMIN_IDS`
- `ADMIN_NOTIFY_IDS`
- `SUB_*`

## Локальный запуск

```bash
pip install -r requirements.txt
python main.py
```

Проверка синтаксиса:

```bash
python -m compileall main.py config.py max_handlers max_keyboards services database tools
```

Локальный smoke без токена:

```bash
python tools/smoke_local.py
```

Probe для live-проверки реального MAX payload:

```bash
python tools/max_payload_probe.py
```

## Docker

```bash
docker compose up -d --build
docker compose logs -f bot
docker compose ps
```

Данные вынесены в volume:
- `./data` -> `/app/data`
- `./media` -> `/app/media`

`MEDIA_TEMP_DIR` используется для временных загрузок, `MEDIA_DEMO_DIR` — для постоянных demo-файлов эффектов.

## Команды пользователя

- `/start`
- `/menu`
- `/balance`
- `/help`
- `/photo_ideas`
- `/photo_edit`
- `/image`
- `/effects`
- `/custom`
- `/concat`
- `/cut`
- `/invite`

## Админ-команды

- `/admin_help`
- `/add_session`
- `/session_del`
- `/sub_on <ID> <amount>`
- `/sub_off <ID>`
- `/sub_check <ID>`
- `/sub_cancel <ID>`
- `/adstats <метка>`
- `/adstats_all`
- `/botstats`
- `/adtag <метка>`
- `/genpromo <кол-во токенов>`
- `/set_top`
- `/get_prompt`
- `/admin_add <ID>`
- `/admin_del <ID>`
- `/admin_list`
