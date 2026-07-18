# mahiru-ai

<p align="center">
  <img src="assets/avatar.png" alt="Mahiru AI" width="600">
</p>

<Живая> виртуальная девушка-компаньонка в Telegram:
своя личность и вкусы, память, живое настроение, пишет первой. Анимешница и геймерша: говорит про
аниме/мангу/манхву/игры со своим мнением, качает мангу/ранобэ с MangaLib, знает цены и отзывы Steam,
гуглит, понимает картинки. 

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![GitHub latest commit](https://badgen.net/github/last-commit/Elytrya/mahiru-ai)](https://GitHub.com/Elytrya/mahiru-ai/commit/)
[![GitHub branches](https://badgen.net/github/branches/Elytrya/mahiru-ai)](https://github.com/Elytrya/mahiru-ai/)
[![GitHub commits](https://badgen.net/github/commits/Elytrya/mahiru-ai)](https://GitHub.com/Elytrya/mahiru-ai/commit/)
[![GitHub issues](https://badgen.net/github/issues/Elytrya/mahiru-ai/)](https://GitHub.com/Elytrya/mahiru-ai/issues/)

## Фичи

- **Живой характер-партнёр**: ведёт себя как настоящий человек со своими потребностями, мнением и настроением, "
а не как услужливый ассистент. Может отказаться отвечать, капризничать, сама делится впечатлениями.
- **Агентная архитектура**: Telegram → AI Core → tool-loop → tools (Anime, MangaLib, Steam, Web, Memory, Vision).
- **Единый интерфейс провайдеров**: Gemini, OpenAI, Claude, DeepSeek, Ollama, **g4f (gpt4free - бесплатно, без ключей)**.
- **Быстрый g4f**: кэш последней рабочей пары (провайдер+модель), параллельная гонка провайдеров с забором первого успешного, жёсткие таймауты и отсев дохлых бэкэндов.
- **Личность в БД**: имя, возраст, характер, стиль, речь, интересы, эмоциональность - редактируется `/set`.
- **Умная память**: LLM-экстрактор вытаскивает важные факты (importance ≥ 60), retrieval по релевантности.
- **Tools**: `web_search`/`google_search`, `anime_search/info`, `lib_search/info/download` (MangaLib - манга/ранобэ/хентай в PDF/CBZ/EPUB/TXT), `steam_search/game/reviews`, `memory_save`, `image_vision`.
- **Скачивание с MangaLib кнопками**: выбор тайтла и глав, формат на выбор; упавшие главы пропускаются, а не рвут весь докач.
- **Steam живым диалогом**: цены/скидки с реакцией, поиск угарных отзывов (в т.ч. по случайной игре) с кнопками «другая игра / ещё отзыв».
- **Mood system**: happy / sad / tired / excited / curious / annoyed / playful / loving - влияет на тон, дрейфует и плавно восстанавливается к нейтральному, не залипая.
- **Автономные сообщения**: APScheduler в расписании, сама пишет первой - делится, что дочитала/прошла, или просто скучает.
- **Админка в Telegram**: `/admin` - Личность, Память, AI, Провайдер, Статистика, Очистка, Экспорт.
- **Кнопка инструментов**: при `SHOW_TOOL_CALLS=true` под ответом/файлом показывается, какой тул был вызван.
- **Стек**: Python 3.12, aiogram 3, SQLAlchemy 2 (async), Redis

## Быстрый старт (туториал)

### 1. Скачай проект

```bash
git clone <свой репо> mahiru && cd mahiru
# или распакуй mahiru.zip
```

### 2. Запусти мастер настройки

```bash
python setup_wizard.py
```

Мастер проведёт через 7 шагов прямо в консоли:

1. **Telegram** - `BOT_TOKEN` (@BotFather) и твой `ADMIN_IDS` (@userinfobot).
2. **AI-провайдер** - выбери из списка:
   - `g4f` - бесплатно, без ключей ([xtekky/gpt4free](https://github.com/xtekky/gpt4free))
   - `gemini` / `openai` / `claude` / `deepseek` - с API-ключом
   - `ollama` - локальные модели
3. **БД** - SQLite (файл) / PostgreSQL / custom.
4. **Google Search** - опционально (без него бот не полезет в интернет).
5. **Автономные сообщения** - окно времени и частота.
6. **`pip install -r requirements.txt`** - мастер сам предложит.
7. **Запуск** - `python bot.py`.

Если запустишь `python bot.py` без `.env` - бот сам предложит запустить мастер.

### 3. Напиши боту `/start` в Telegram

Готово. Админка - `/admin`. Редактировать личность - `/set name Mahiru`, `/set character "милая, дерзкая"`.

## g4f (gpt4free) - бесплатный доступ

[xtekky/gpt4free](https://github.com/xtekky/gpt4free) агрегирует публичные бэкэнды (OpenaiChat,
HuggingChat, You, Bing…) в единый API. Ключи не нужны.

- `G4F_MODEL` - `gpt-4o-mini`, `gpt-4o`, `claude-3-5-sonnet`, `llama-3.1-70b` и др.
- `G4F_PROVIDER` - принудительный бэкэнд (пусто → auto).
- Сменить модель на лету: `/admin → Провайдер`.

Важно: публичные бэкэнды нестабильны, таймауты и ошибки обычны. Для production
лучше платный ключ (Gemini free tier - отличный компромисс).

## Структура

```
mahiru/
├─ bot.py                  # entry point (с проверкой first-run)
├─ setup_wizard.py         # интерактивная настройка
├─ config.py               # pydantic Settings
├─ ai/
│  ├─ core.py              # AI Core с tool-loop
│  ├─ prompts.py           # system prompt личности
│  ├─ mood.py              # mood drift
│  └─ providers/           # gemini | openai | claude | deepseek | ollama | g4f
├─ memory/                 # анализатор + storage + manager
├─ methods/                # tools: anime, manga, google, memory, image
├─ handlers/               # aiogram: messages, admin, callbacks
├─ scheduler/              # автономные сообщения
├─ db/                     # SQLAlchemy модели и репозиторий
└─ utils/                  # logger, redis-кэш
```

## Как добавить свой tool

```python
# methods/my_tool/hello.py
from methods.base import Tool

class HelloTool(Tool):
    name = "hello"
    description = "Сказать привет"
    parameters = {"type": "object", "properties":
                  {"name": {"type": "string"}}, "required": ["name"]}

    async def run(self, args, *, session, user_id: int):
        return {"reply": f"Привет, {args['name']}!"}
```

Зарегистрируй в `methods/registry.py` - AI сама вызовет, когда потребуется.

## Как добавить свой AI-провайдер

Создай `ai/providers/my.py`, наследуй `BaseProvider`, реализуй `chat()`, добавь в
`REGISTRY` в `factory.py`. Всё.

## License

 GPL-3.0
