# План миграции Telegram -> MAX

Дата старта текущей миграции: 2026-05-18  
Исходник: `telegram_video_bot`  
Рабочий MAX-проект: корень репозитория

## Принцип

Сохраняем бизнес-ядро и продукт:
- БД и CRUD;
- подписки, баланс, транзакции, pending actions;
- ЮKassa и автосписания;
- Kie.ai / Replicate;
- FFmpeg-инструменты;
- админку, промокоды, UTM/ref deeplinks;
- smart-рассылку.

Меняем только транспорт:
- Telegram `aiogram` -> MAX `maxapi`;
- Telegram keyboards -> MAX inline attachments;
- Telegram `file_id` -> URL/local media source;
- Telegram Stars не переносятся; в MAX оставлены только две подписки ЮKassa.

## Этапы

### Этап 0. Инвентаризация — завершен

Изучено:
- `telegram_video_bot/main.py`
- `telegram_video_bot/config.py`
- `telegram_video_bot/handlers/*`
- `telegram_video_bot/keyboards/*`
- `telegram_video_bot/services/*`
- `telegram_video_bot/database/*`
- корневой `TELEGRAM_TO_MAX_AGENT_GUIDE.md`

Найдены Telegram-зависимости:
- `aiogram` routers/filters/FSM;
- Telegram callbacks и inline keyboards;
- Telegram media `file_id`;
- Telegram Stars invoices;
- Telegram command scopes.

### Этап 1. Рабочий MAX-каркас — завершен

Создано в корне:
- `main.py`
- `config.py`
- `.env.example`
- `requirements.txt`
- `max_handlers/`
- `max_keyboards/`
- `services/max_adapter.py`

`main.py`:
- загружает `Config`;
- инициализирует SQLite;
- запускает `maxapi` `Dispatcher`;
- подключает routers;
- устанавливает команды;
- запускает `subscription_watcher`, `pending_yookassa_watcher`, `smart_mailing_loop`;
- поддерживает polling и webhook через `MAX_USE_WEBHOOK`.

### Этап 2. Перенос пользовательских сценариев — первый проход завершен

Перенесено:
- `/start` с payload `ref_`, `promo_`, UTM;
- главное меню;
- помощь;
- инвайт-ссылка;
- баланс;
- видео-эффекты;
- фото-эффекты;
- свой промпт для видео;
- ИИ-Фотошоп;
- текст -> изображение;
- склейка видео;
- вырезание фрагмента.

FSM реализован в `max_handlers/state.py`.

### Этап 3. Монетизация — первый проход завершен

Перенесено:
- выбор тарифа;
- ЮKassa redirect payment;
- polling статуса платежа;
- активация подписки;
- pending action после оплаты;
- ручное продление;
- отключение автопродления;
- фоновое автосписание.

Текущая модель:
- только две подписки ЮKassa с автопродлением: неделя и месяц;
- разовая покупка отключена.

### Этап 4. Админка и рассылка — первый проход завершен

Перенесено:
- `/admin_help`
- `/add_session`
- `/session_del`
- `/sub_on`
- `/sub_off`
- `/sub_check`
- `/sub_cancel`
- `/adstats`
- `/adstats_all`
- `/botstats`
- `/adtag`
- `/genpromo`
- `/set_top`
- `/get_prompt`
- `/admin_add`
- `/admin_del`
- `/admin_list`

Перенесена `smart_mailing_loop` под MAX-адаптер.

Дополнено:
- админские уведомления о генерациях показывают пользователя, тип генерации, шаблон/промпт, стоимость и длительность;
- уведомления об оплатах ЮKassa показывают пользователя, тариф, сумму, токены и автопродление;
- уведомления об отключении подписки показывают тариф и дату окончания доступа;
- smart-рассылка отправляет demo-фото/demo-видео через MAX, если у эффекта есть локальный demo-файл, и оставляет текстовый fallback.

### Этап 5. Проверка — частично завершен

Выполнено:
- `python -m compileall main.py config.py max_handlers max_keyboards services database`
- проверена сборка MAX inline-клавиатур;
- проверено создание SQLite-схемы на smoke-базе;
- проверено отсутствие `aiogram` в корневом MAX-коде.
- добавлен и пройден `python tools/smoke_local.py`;
- добавлен `tools/max_payload_probe.py` для live-проверки реальных MAX update payload;
- добавлен отдельный обработчик `bot_started`, чтобы deeplink payload работал не только через текстовый `/start`;
- smart-рассылка получила fallback на текст, если демо осталось Telegram `file_id` и не отправляется в MAX.
- pending actions с фото теперь кешируют входящее MAX-медиа в `MEDIA_TEMP_DIR`, чтобы после оплаты не зависеть от временного URL.
- expired/canceled YooKassa pending payments чистят связанный pending media cache.
- pending-payment guard блокирует любую активную pending-оплату пользователя.
- `database/seed_effects.py` переведен на `DATABASE_PATH` из общего конфига.
- добавлен `.dockerignore` для безопасного Docker-контекста без `.env`, локальных БД/медиа/cache и `telegram_video_bot`.
- `requirements.txt` закрепляет `maxapi==1.0.0`, под который проверялась текущая реализация.
- admin-demo из MAX сохраняются в `MEDIA_DEMO_DIR`, чтобы не хранить временные attachment URL.
- `database/seed_effects.py` больше не записывает старые Telegram `file_id` в demo-поля и не затирает существующие MAX-demo.
- `MAX_BOT_LINK_BASE` может быть полным MAX URL бота; deeplink и YooKassa return URL строятся через общий helper.
- `Dispatcher` переведен на `use_create_task=True`, чтобы долгие генерации, платежные запросы и инструменты не останавливали обработку новых callbacks.
- На время генерации пользовательский state переводится в `generation_running`; меню и команды остаются доступны, а старое ожидание фото/промпта не запускает повторный сценарий.
- Навигация по страницам эффектов использует callback-ответ MAX с обновленным текстом и клавиатурой, если API/клиент поддерживает редактирование исходного сообщения.
- Админ-команды MAX сверены с Telegram-эталоном: формат HTML-ответов, статистика, промпты эффектов, списки удаления/ТОПа, промокоды, owner-список админов.
- Админские уведомления FFmpeg-инструментов и smart-рассылки форматируются в HTML и показывают ключевые детали действия.
- Карточка баланса повторяет Telegram-логику: `✅ Подписка активна` показывается только при `status='active'` и `auto_renew=1`; отключенное автопродление считается неактивной подпиской в UI.
- MAX-клавиатура длительности разбита по 3 кнопки в строке, чтобы API не отклонял `Создать видео` с `errors.maxRowSize`.
- Для Replicate входные MAX-фото передаются как base64 локально скачанного файла, а не как временный MAX attachment URL.
- Видео-эффекты используют Replicate fallback, если Kie.ai не может создать задачу из-за ошибки провайдера.

Осталось:
- live smoke в MAX с настоящим `MAX_BOT_TOKEN`;
- проверка входящих фото/видео attachment payload на реальных сообщениях MAX;
- проверка загрузки результата Kie/Replicate в MAX;
- проверка ЮKassa с тестовым платежом;
- проверка webhook-режима на сервере;
- проверка smart-рассылки на малом списке пользователей.

## Риски

1. MAX media attachments могут отличаться по форме payload от локальной версии `maxapi`. В `max_handlers/utils.py` сделан универсальный поиск URL, но его нужно подтвердить live-сообщением через `tools/max_payload_probe.py`.
2. Старые demo `file_id` из Telegram не будут отправляться в MAX. В пользовательских сценариях и smart-рассылке есть fallback без демо, но новые demo нужно добавлять через MAX-админку или миграцией в URL/файлы.
3. MAX не имеет Telegram Stars. Разовые покупки отключены, монетизация идет только через две подписки ЮKassa.
4. In-memory FSM сбросится при перезапуске процесса. Для production это допустимо на первом этапе, но для долгих сценариев можно вынести state в SQLite.
5. Webhook нужно проверять на сервере с публичным HTTPS URL и одним активным экземпляром бота.

## Журнал работ

### 2026-05-18

- Создан корневой MAX-проект.
- Скопировано платформенное ядро из `telegram_video_bot`.
- Добавлены `max_handlers`, `max_keyboards`, `services/max_adapter.py`.
- Переписан `config.py` под MAX и сохранены продуктовые переменные.
- Переписаны `services/notify.py`, `services/balance_card.py`, `services/subscription_tasks.py`, `services/smart_mailer.py`.
- Адаптирован `services/generation.py` под MAX-адаптер.
- Реализованы пользовательские сценарии, платежи, pending actions, админка, FFmpeg-инструменты.
- Обновлены `README.md` и `MAX_MIGRATION_PLAN.md`.

## Ближайший следующий этап

После выдачи `MAX_BOT_TOKEN`:
1. Запустить polling локально.
2. Проверить `/start`, меню и callbacks.
3. Отправить фото в каждый фото/видео сценарий и посмотреть фактический attachment payload.
4. При необходимости поправить `get_media_source`.
5. Проверить тестовую ЮKassa-оплату и pending action.

## Деплой 2026-05-19

- GitHub: `https://github.com/NNFall/maxvideobot`, ветка `main`.
- Сервер: `185.171.83.116`.
- Рабочая папка: `/root/maxvideobot`.
- Секреты хранятся только в серверном `/root/maxvideobot/.env`, файл не коммитится.
- Docker Compose запущен с внешними volume:
  - `/root/maxvideobot/data` -> `/app/data`;
  - `/root/maxvideobot/media` -> `/app/media`.
- База SQLite: `/root/maxvideobot/data/database.db`.
- Media temp/demo:
  - `/root/maxvideobot/media/temp`;
  - `/root/maxvideobot/media/demos`.
- Проверка после деплоя: контейнер `maxvideobot-bot-1` running, restart count `0`, polling стартовал, бот авторизован как `@id644009650098_3_bot`.
