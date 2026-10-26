"""Справочник категорий и отнесение позиций к категориям (ФТ-14, ФТ-15, ФТ-26)."""
import re
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.integrations.ml_client import MlClient, MlUnavailable
from app.modules.classification.models import Category, UserCategoryRule

UNCATEGORIZED = "Без категории"

DEFAULT_CATEGORIES = [
    "Продукты", "Готовая еда", "Бытовая химия", "Аптека и здоровье", "Одежда и обувь",
    "Транспорт", "Дом и ремонт", "Детские товары", "Животные", "Красота и гигиена",
    "Развлечения", "Электроника", "Спорт", "Подарки", "Прочее", UNCATEGORIZED,
]


@dataclass
class Classified:
    category_id: int
    confidence: float


def normalize(name: str) -> str:
    """Приводит название позиции к виду, по которому ищется правило пользователя."""
    text = name.lower().replace("ё", "е")
    text = re.sub(r"\d+(?:[.,]\d+)?\s*(?:%|(?:кг|мл|шт|уп|г|л)\b)", " ", text)  # жирность, вес, объём, количество
    text = re.sub(r"[^a-zа-я ]+", " ", text)  # остальные цифры и знаки только мешают сопоставлению
    return re.sub(r"\s+", " ", text).strip()


def seed_categories(session: Session) -> None:
    existing = set(session.scalars(select(Category.name)))
    session.add_all(Category(name=n) for n in DEFAULT_CATEGORIES if n not in existing)
    session.commit()


def list_categories(session: Session, only_active: bool = True) -> list[Category]:
    query = select(Category).order_by(Category.name)
    if only_active:
        query = query.where(Category.is_active)
    return list(session.scalars(query))


def create_category(session: Session, name: str) -> Category:
    if session.scalar(select(Category).where(Category.name == name)) is not None:
        raise Conflict("Такая категория уже есть")
    category = Category(name=name)
    session.add(category)
    session.flush()
    return category


def update_category(session: Session, category_id: int, name: str | None, is_active: bool | None) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise NotFound("Категория не найдена")
    if name is not None:
        category.name = name
    if is_active is not None:
        category.is_active = is_active
    session.flush()
    return category


def get_category(session: Session, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if category is None or not category.is_active:
        raise NotFound("Категория не найдена")
    return category


def uncategorized_id(session: Session) -> int:
    category = session.scalar(select(Category).where(Category.name == UNCATEGORIZED))
    if category is None:
        category = create_category(session, UNCATEGORIZED)
    return category.id


def remember_choice(session: Session, user_id: int, item_name: str, category_id: int) -> None:
    """Запоминает выбор пользователя. Транзакцию подтверждает вызывающий."""
    key = normalize(item_name)
    if not key:
        return
    rule = session.scalar(
        select(UserCategoryRule).where(UserCategoryRule.user_id == user_id, UserCategoryRule.normalized_name == key)
    )
    if rule is None:
        session.add(UserCategoryRule(user_id=user_id, normalized_name=key, category_id=category_id))
    else:
        rule.category_id = category_id


def classify_items(session: Session, user_id: int, names: list[str], ml: MlClient) -> list[Classified]:
    """Правило пользователя сильнее модели. Если модель недоступна, позиция остаётся без категории."""
    fallback = uncategorized_id(session)
    by_name = {c.name: c.id for c in list_categories(session)}
    try:
        predictions = ml.classify(names)
    except MlUnavailable:
        predictions = [None] * len(names)
    keys = [normalize(n) for n in names]
    rules = {
        r.normalized_name: r.category_id
        for r in session.scalars(
            select(UserCategoryRule).where(UserCategoryRule.user_id == user_id, UserCategoryRule.normalized_name.in_(keys))
        )
    }
    result = []
    for key, prediction in zip(keys, predictions):
        if key in rules:
            result.append(Classified(rules[key], 1.0))
        elif prediction is not None and prediction.category in by_name:
            result.append(Classified(by_name[prediction.category], prediction.confidence))
        else:
            result.append(Classified(fallback, 0.0))
    return result


def delete_user_data(session: Session, user_id: int) -> None:
    session.execute(delete(UserCategoryRule).where(UserCategoryRule.user_id == user_id))
