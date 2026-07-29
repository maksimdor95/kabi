"""Тесты M7: TG, career HTML, Getmatch, Habr (без сети)."""

from app.ingestion.jobs.career_sites_connector import load_career_config, parse_html_list
from app.ingestion.jobs.getmatch_connector import (
    enrich_from_vacancy_html,
    parse_getmatch_channel,
)
from app.ingestion.jobs.habr_connector import parse_habr_html, parse_habr_rss
from app.ingestion.jobs.tg_connector import load_tg_config, parse_channel_html
from app.ingestion.runner import default_job_connectors

_FIXTURE_TG = """
<div class="tgme_widget_message_wrap">
  <a class="tgme_widget_message_date" href="https://t.me/forproducts/10190"></a>
  <div class="tgme_widget_message_text js-message_text">
    Head of Product<br/>Москва, hybrid.<br/>
    <a href="https://boards.greenhouse.io/acme/jobs/123">Описание</a>
  </div>
</div>
<div class="tgme_widget_message_wrap">
  <a class="tgme_widget_message_date" href="https://t.me/forproducts/10191"></a>
  <div class="tgme_widget_message_text js-message_text">
    Курьер на велосипеде, без опыта, 50к
  </div>
</div>
"""

_FIXTURE_GETMATCH = """
<div class="tgme_widget_message_wrap">
  <div class="tgme_widget_message_text js-message_text">
    🔶 Head of Product, Avito Локация: #Москва #Удаленка
    <a href="https://getmatch.ru/vacancies/35399">Откликнуться</a>
  </div>
</div>
<div class="tgme_widget_message_wrap">
  <div class="tgme_widget_message_text js-message_text">
    🔶 Курьер Сбер Локация: #Москва
    <a href="https://getmatch.ru/vacancies/111">Откликнуться</a>
  </div>
</div>
"""

_FIXTURE_HABR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Требуется «Product Owner / Product Lead» (Екатеринбург, от 200 000 до 320 000 ₽)</title>
    <description>Компания «БИЗМОЛЛ» ищет хорошего специалиста на вакансию «Product Owner».</description>
    <author>БИЗМОЛЛ</author>
    <link>https://career.habr.com/vacancies/1000166562</link>
    <guid>1000166562</guid>
  </item>
  <item>
    <title>Требуется «Курьер» (Москва)</title>
    <description>Доставка еды</description>
    <author>Delivery</author>
    <link>https://career.habr.com/vacancies/1</link>
    <guid>1</guid>
  </item>
</channel></rss>
"""

_FIXTURE_HABR_HTML = """
<div class="vacancy-card">
  <a aria-label="Head of Product" class="vacancy-card__backdrop-link" href="/vacancies/1000999"></a>
  <div class="vacancy-card__inner">
    <div class="vacancy-card__company">
      <a class="link-comp link-comp--appearance-dark" href="/companies/acme">Acme</a>
    </div>
    <div class="vacancy-card__salary">от 500 000 ₽</div>
    <div class="vacancy-card__meta">можно удалённо</div>
  </div>
</div>
<div class="vacancy-card">
  <a aria-label="Курьер" class="vacancy-card__backdrop-link" href="/vacancies/2"></a>
  <div class="vacancy-card__inner">
    <div class="vacancy-card__company">
      <a class="link-comp link-comp--appearance-dark" href="/companies/x">X</a>
    </div>
  </div>
</div>
"""


def test_tg_config_has_must_channels():
    cfg = load_tg_config()
    names = {c["username"] for c in cfg["channels"]}
    assert {"forproducts", "forchiefs", "nrgjobs", "HRity"} <= names


def test_parse_channel_keeps_product_drops_courier():
    drafts = parse_channel_html(
        _FIXTURE_TG,
        username="forproducts",
        relevance_any=["product", "продукт", "head of product"],
        limit=25,
    )
    assert len(drafts) == 1
    assert drafts[0].title.startswith("Head of Product")
    assert drafts[0].source == "tg_forproducts"
    assert drafts[0].external_id == "forproducts_10190"
    assert "greenhouse" in (drafts[0].url or "")


def test_parse_html_career_filters_by_title():
    html = """
    <a href="/vacancies/product/12345/">Head of Product</a>
    <a href="/vacancies/courier/9/">Курьер</a>
    <a href="/teams/job/">Карьера</a>
    <a href="/about">О компании</a>
    """
    drafts = parse_html_list(
        html,
        site_id="avito",
        company="Авито",
        list_url="https://career.avito.com/vacancies/",
        link_contains=["/vacancies/"],
        relevance=["product", "продукт", "head of"],
        path_regex=r"/vacancies/[^/]+/\d+",
        path_exclude=["/teams/job/"],
    )
    assert len(drafts) == 1
    assert drafts[0].org == "Авито"
    assert drafts[0].source == "career_avito"
    assert drafts[0].external_id == "12345"


def test_career_yaml_lists_bigtech():
    cfg = load_career_config()
    ids = {s["id"] for s in cfg["sites"]}
    assert {"yandex", "sber", "tbank", "avito", "vk", "alfa", "ozon", "mts", "wildberries"} <= ids
    enabled = {s["id"] for s in cfg["sites"] if s.get("enabled", True)}
    assert "avito" in enabled and "vk" in enabled and "yandex" in enabled
    assert "sber" not in enabled  # SPA без SSR


def test_getmatch_keeps_product_drops_courier():
    drafts = parse_getmatch_channel(
        _FIXTURE_GETMATCH,
        relevance=["product", "продукт", "head of"],
    )
    assert len(drafts) == 1
    assert drafts[0].source == "getmatch.ru"
    assert drafts[0].external_id == "35399"
    assert "Head of Product" in drafts[0].title
    assert drafts[0].remote is True


def test_getmatch_enrich_title():
    from app.ingestion.schemas import OpportunityDraft

    d = OpportunityDraft(
        type="job",
        title="🔶 long messy title from tg channel about something",
        url="https://getmatch.ru/vacancies/1",
        source="getmatch.ru",
        external_id="1",
    )
    html = "<title>Вакансия Head of Product, работа в Avito, в Москве — getmatch</title>"
    enrich_from_vacancy_html(html, d)
    assert d.title == "Head of Product"
    assert d.org == "Avito"


def test_habr_rss_and_html():
    rss = parse_habr_rss(
        _FIXTURE_HABR_RSS,
        relevance=["product", "продукт", "owner", "lead"],
    )
    assert len(rss) == 1
    assert rss[0].title.startswith("Product Owner")
    assert rss[0].org == "БИЗМОЛЛ"
    assert rss[0].source == "career.habr.com"
    assert rss[0].salary and rss[0].salary["min"] == 200000

    html = parse_habr_html(
        _FIXTURE_HABR_HTML,
        relevance=["product", "head of"],
    )
    assert len(html) == 1
    assert html[0].title == "Head of Product"
    assert html[0].org == "Acme"
    assert html[0].remote is True
    assert html[0].salary and html[0].salary["min"] == 500000


def test_default_connectors_include_m7bd():
    sources = [c.source for c in default_job_connectors()]
    assert "getmatch.ru" in sources
    assert "career.habr.com" in sources
    assert "career_sites" in sources
