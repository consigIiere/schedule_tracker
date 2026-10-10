import asyncio
from datetime import date, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

import db
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")


bot = Bot(token=TOKEN)
dp = Dispatcher()

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_NAMES = {
    "mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт",
    "fri": "Пт", "sat": "Сб", "sun": "Нд"
}

def get_week_cycle_number(target_date: date) -> int:
    iso_week = target_date.isocalendar()[1]
    return 1 if (iso_week % 2 != 0) else 2

def get_day_rule(target_date: date) -> str:
    week_num = get_week_cycle_number(target_date)
    day_code = WEEKDAYS[target_date.weekday()]
    return f"w{week_num}_{day_code}"

def format_workout_display(lines: list) -> str:
    cleaned_lines = [item.strip() for item in lines if item.strip()]
    return "\n".join(cleaned_lines)

class Form(StatesGroup):
    waiting_single_task = State()
    waiting_daily_task = State()
    waiting_workout_week = State()
    waiting_workout_day = State()
    waiting_workout_exercises = State()

# --- КЛАВІАТУРИ ---
def build_schedule_keyboard(tasks: list, cur_date: date, delete_mode: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    
    if delete_mode:
        for t in tasks:
            rule = t["rule"]
            if rule == "daily":
                prefix = "🔁"
            elif rule and rule.startswith("w"):
                prefix = "🏋️"
            else:
                prefix = "📌"
            
            btn_text = f"{prefix} {t['title']}"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"del_task:{t['id']}:{cur_date.isoformat()}")])
            
        buttons.append([InlineKeyboardButton(text="◀️ Готово / До відміток", callback_data=f"date:{cur_date.isoformat()}")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    for t in tasks:
        icon = "✅" if t["is_done"] else "❌"
        buttons.append([InlineKeyboardButton(text=f"{icon} {t['title']}", callback_data=f"toggle:{t['id']}:{cur_date.isoformat()}")])

    prev_d = (cur_date - timedelta(days=1)).isoformat()
    next_d = (cur_date + timedelta(days=1)).isoformat()

    buttons.append([
        InlineKeyboardButton(text="◀️ Вчора", callback_data=f"date:{prev_d}"),
        InlineKeyboardButton(text="Сьогодні", callback_data=f"date:{date.today().isoformat()}"),
        InlineKeyboardButton(text="Завтра ▶️", callback_data=f"date:{next_d}")
    ])
    buttons.append([
        InlineKeyboardButton(text="➕ Разове завдання", callback_data=f"add_single:{cur_date.isoformat()}"),
        InlineKeyboardButton(text="🗑 Видалити завдання дня", callback_data=f"enter_del_mode:{cur_date.isoformat()}")
    ])
    buttons.append([
        InlineKeyboardButton(text="⚙️ Налаштувати розклад", callback_data="manage_templates")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_manage_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Додати щоденну звичку", callback_data="tpl_add_daily")],
        [InlineKeyboardButton(text="🏋️ Додати сет вправ на тиждень", callback_data="tpl_pick_week")],
        [InlineKeyboardButton(text="📋 Щоденні звички", callback_data="tpl_daily_list")],
        [InlineKeyboardButton(text="◀️ До розкладу", callback_data=f"date:{date.today().isoformat()}")]
    ])

def cancel_keyboard(back_callback: str = "manage_templates") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати введення", callback_data=back_callback)]
    ])

# Рендеринг розкладу
async def render_schedule(event: Message | CallbackQuery, state: FSMContext, user_id: int, target_date: date, delete_mode: bool = False):
    day_rule = get_day_rule(target_date)
    week_num = get_week_cycle_number(target_date)
    day_name = WEEKDAY_NAMES[WEEKDAYS[target_date.weekday()]]
    
    await db.ensure_day_tasks(user_id, target_date, day_rule)
    tasks = await db.get_day_tasks_with_type(user_id, target_date)
    kb = build_schedule_keyboard(tasks, target_date, delete_mode=delete_mode)
    
    if delete_mode:
        text = (
            f"**Режим видалення на {target_date.isoformat()}**\n\n"
            f"Обери, що прибрати:\n"
            f"• 📌 — разові справи\n"
            f"• 🔁 — щоденні звички"
        )
    else:
        text = (
            f"📅 **{target_date.isoformat()}** ({day_name}) — **Тиждень {week_num}**\n"
        )

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        await event.answer()
    else:
        clean_kb_msg = await event.answer("Завантаження...", reply_markup=ReplyKeyboardRemove())
        await clean_kb_msg.delete()
        
        new_msg = await event.answer(text, reply_markup=kb, parse_mode="Markdown")
        await state.update_data(main_window_id=new_msg.message_id)

# --- ХЕНДЛЕРИ РОЗКЛАДУ ---
@dp.message(Command("start", "schedule"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await render_schedule(message, state, message.from_user.id, date.today())

@dp.callback_query(F.data.startswith("date:"))
async def cb_date(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _, date_str = callback.data.split(":")
    cur_date = date.fromisoformat(date_str)
    await render_schedule(callback, state, callback.from_user.id, cur_date)

@dp.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(callback: CallbackQuery):
    _, task_id, date_str = callback.data.split(":")
    cur_date = date.fromisoformat(date_str)
    await db.toggle_task(int(task_id), callback.from_user.id)
    tasks = await db.get_day_tasks_with_type(callback.from_user.id, cur_date)
    kb = build_schedule_keyboard(tasks, cur_date)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

# --- РЕЖИМ ВИДАЛЕННЯ ---
@dp.callback_query(F.data.startswith("enter_del_mode:"))
async def cb_del_mode(callback: CallbackQuery, state: FSMContext):
    _, date_str = callback.data.split(":")
    cur_date = date.fromisoformat(date_str)
    await render_schedule(callback, state, callback.from_user.id, cur_date, delete_mode=True)

@dp.callback_query(F.data.startswith("del_task:"))
async def cb_delete_day_task(callback: CallbackQuery, state: FSMContext):
    _, task_id, date_str = callback.data.split(":")
    cur_date = date.fromisoformat(date_str)
    await db.delete_task_completely(int(task_id), callback.from_user.id)
    await callback.answer("Видалено!")
    await render_schedule(callback, state, callback.from_user.id, cur_date, delete_mode=True)

# --- ДОДАВАННЯ РАЗОВОЇ СПРАВИ ---
@dp.callback_query(F.data.startswith("add_single:"))
async def cb_add_single(callback: CallbackQuery, state: FSMContext):
    _, date_str = callback.data.split(":")
    await state.update_data(target_date=date_str, window_msg_id=callback.message.message_id)
    await state.set_state(Form.waiting_single_task)
    await callback.message.edit_text(
        f"Введи разове завдання на **{date_str}**:",
        reply_markup=cancel_keyboard(f"date:{date_str}"),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(Form.waiting_single_task)
async def process_single_task(message: Message, state: FSMContext):
    data = await state.get_data()
    cur_date = date.fromisoformat(data["target_date"])
    window_msg_id = data.get("window_msg_id")
    await db.add_single_task(message.from_user.id, cur_date, message.text.strip())
    
    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    
    day_rule = get_day_rule(cur_date)
    week_num = get_week_cycle_number(cur_date)
    day_name = WEEKDAY_NAMES[WEEKDAYS[cur_date.weekday()]]
    await db.ensure_day_tasks(message.from_user.id, cur_date, day_rule)
    tasks = await db.get_day_tasks_with_type(message.from_user.id, cur_date)
    kb = build_schedule_keyboard(tasks, cur_date)
    text = (
        f"📅 **{cur_date.isoformat()}** ({day_name}) — **Тиждень {week_num}**\n"
        f"_(натискай на завдання, щоб відмітити)_"
    )
    if window_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=window_msg_id,
                text=text,
                reply_markup=kb,
                parse_mode="Markdown"
            )
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- КОНСТРУКТОР ТА ШАБЛОНИ ---
@dp.callback_query(F.data == "manage_templates")
async def cb_manage(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "⚙️ **Конструктор розкладу**\nОбери потрібну дію:",
        reply_markup=build_manage_keyboard(),
        parse_mode="Markdown"
    )
    await state.update_data(main_window_id=callback.message.message_id)
    await callback.answer()

@dp.callback_query(F.data == "tpl_add_daily")
async def cb_tpl_daily(callback: CallbackQuery, state: FSMContext):
    await state.update_data(window_msg_id=callback.message.message_id)
    await state.set_state(Form.waiting_daily_task)
    await callback.message.edit_text(
        "Введи щоденну справу (з'являтиметься щодня):",
        reply_markup=cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(Form.waiting_daily_task)
async def process_daily(message: Message, state: FSMContext):
    data = await state.get_data()
    window_msg_id = data.get("window_msg_id")
    await db.add_template(message.from_user.id, message.text.strip(), "daily")
    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    
    text = f"✅ Щоденну звичку «{message.text.strip()}» додано!\n\n⚙️ **Конструктор розкладу**:"
    kb = build_manage_keyboard()
    if window_msg_id:
        try:
            await message.bot.edit_message_text(chat_id=message.chat.id, message_id=window_msg_id, text=text, reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb)

# Додавання та вибір тижня
@dp.callback_query(F.data == "tpl_pick_week")
async def cb_pick_week(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔵 Тиждень 1", callback_data="set_week:w1")],
        [InlineKeyboardButton(text="🟢 Тиждень 2", callback_data="set_week:w2")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="manage_templates")]
    ])
    await callback.message.edit_text("Обери, для якого тижня налаштувати вправи:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_week:"))
async def cb_chosen_week(callback: CallbackQuery, state: FSMContext):
    _, week_prefix = callback.data.split(":")
    await state.update_data(chosen_week=week_prefix)
    week_title = "Тижня 1" if week_prefix == "w1" else "Тижня 2"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=WEEKDAY_NAMES[day], callback_data=f"set_day:{day}") for day in WEEKDAYS[:4]],
        [InlineKeyboardButton(text=WEEKDAY_NAMES[day], callback_data=f"set_day:{day}") for day in WEEKDAYS[4:]],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="tpl_pick_week")]
    ])
    await callback.message.edit_text(f"Обери день тренування для **{week_title}**:", reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

# Відображення існуючих вправ дня
@dp.callback_query(F.data.startswith("set_day:"))
async def cb_chosen_day(callback: CallbackQuery, state: FSMContext):
    _, day_code = callback.data.split(":")
    await state.update_data(chosen_day=day_code, window_msg_id=callback.message.message_id)
    data = await state.get_data()
    week_prefix = data["chosen_week"]
    week_str = "1" if week_prefix == "w1" else "2"
    day_name = WEEKDAY_NAMES[day_code]
    rule = f"{week_prefix}_{day_code}"

    existing = await db.get_workout_day_templates(callback.from_user.id, rule)

    if existing:
        raw_lines = [row['title'].replace('🏋️ ', '') for row in existing]
        exercises_text = format_workout_display(raw_lines)
        
        text = (
            f"🏋️ **{day_name} (Тиждень {week_str})**\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"{exercises_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Замінити / Редагувати", callback_data=f"input_exercises:{rule}")],
            [InlineKeyboardButton(text="🗑 Очистити цей день", callback_data=f"clear_day:{rule}")],
            [InlineKeyboardButton(text="◀️ Назад до днів", callback_data=f"set_week:{week_prefix}")]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await start_exercise_input(callback, state, rule, week_str, day_name)
    
    await callback.answer()

@dp.callback_query(F.data.startswith("clear_day:"))
async def cb_clear_day(callback: CallbackQuery, state: FSMContext):
    _, rule = callback.data.split(":")
    week_prefix, day_code = rule.split("_")
    week_str = "1" if week_prefix == "w1" else "2"
    day_name = WEEKDAY_NAMES[day_code]

    await db.clear_workout_day_templates(callback.from_user.id, rule)
    await callback.answer("Вправи цього дня видалено!")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Додати нові вправи", callback_data=f"input_exercises:{rule}")],
        [InlineKeyboardButton(text="◀️ До вибору днів", callback_data=f"set_week:{week_prefix}")]
    ])
    await callback.message.edit_text(
        f"✅ Розклад на **{day_name} (Тиждень {week_str})** повністю очищено.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("input_exercises:"))
async def cb_input_exercises(callback: CallbackQuery, state: FSMContext):
    _, rule = callback.data.split(":")
    week_prefix, day_code = rule.split("_")
    week_str = "1" if week_prefix == "w1" else "2"
    day_name = WEEKDAY_NAMES[day_code]
    
    await state.update_data(chosen_week=week_prefix, chosen_day=day_code, window_msg_id=callback.message.message_id)
    await state.set_state(Form.waiting_workout_exercises)

    existing = await db.get_workout_day_templates(callback.from_user.id, rule)
    
    if existing:
        raw_text = "\n".join([row['title'].replace('🏋️ ', '') for row in existing])
        text = (
            f"✏️ **Редагування: {day_name} (Тиждень {week_str})**\n\n"
            f"Скопіюй текст нижче (клікни по ньому), відредагуй та надішли сюди:\n\n"
            f"```\n{raw_text}\n```"
        )
    else:
        text = (
            f"➕ **{day_name} (Тиждень {week_str})**\n\n"
            f"Надішли вправи стовпчиком (кожну з нового рядка):"
        )

    await callback.message.edit_text(
        text,
        reply_markup=cancel_keyboard(f"set_week:{week_prefix}"),
        parse_mode="Markdown"
    )
    await callback.answer()

async def start_exercise_input(callback: CallbackQuery, state: FSMContext, rule: str, week_str: str, day_name: str):
    week_prefix, day_code = rule.split("_")
    await state.update_data(chosen_week=week_prefix, chosen_day=day_code, window_msg_id=callback.message.message_id)
    await state.set_state(Form.waiting_workout_exercises)
    
    await callback.message.edit_text(
        f"➕ **{day_name} (Тиждень {week_str})**\n\n"
        f"Надішли список вправ у чат (кожну з нового рядка):",
        reply_markup=cancel_keyboard(f"set_week:{week_prefix}"),
        parse_mode="Markdown"
    )

@dp.message(Form.waiting_workout_exercises)
async def process_workout_exercises(message: Message, state: FSMContext):
    data = await state.get_data()
    rule = f"{data['chosen_week']}_{data['chosen_day']}"
    week_str = "1" if data["chosen_week"] == "w1" else "2"
    day_label = WEEKDAY_NAMES[data['chosen_day']]
    window_msg_id = data.get("window_msg_id")

    await db.clear_workout_day_templates(message.from_user.id, rule)

    lines = [line.strip() for line in message.text.split("\n") if line.strip()]
    for exercise in lines:
        title = f"🏋️ {exercise}"
        await db.add_template(message.from_user.id, title, rule)

    formatted_text = format_workout_display(lines)

    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    
    text = (
        f"✅ **Збережено: {day_label} (Тиждень {week_str})**\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{formatted_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    kb = build_manage_keyboard()
    if window_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=window_msg_id,
                text=text,
                reply_markup=kb,
                parse_mode="Markdown"
            )
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- СПИСОК ЩОДЕННИХ ЗВИЧОК ---
@dp.callback_query(F.data == "tpl_daily_list")
async def cb_tpl_daily_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = await db.get_daily_templates(callback.from_user.id)
    if not rows:
        text = "📋 У тебе ще немає збережених щоденних звичок."
    else:
        text = "📋 **Твої щоденні звички:**\n\n"
        for row in rows:
            text += f"• **{row['title']}**\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ До налаштувань", callback_data="manage_templates")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

async def main():
    await db.init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="🚀 Відкрити розклад / Скинути")
    ])
    print("=========================================")
    print("БОТА ЗАПУЩЕННО")
    print("=========================================")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())