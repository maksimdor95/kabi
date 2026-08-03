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
    channels = [c for c in cfg["channels"] if isinstance(c, dict) and c.get("username")]
    names = {c["username"] for c in channels}
    assert len(channels) == 23
    assert all(c.get("priority") == "must" for c in channels)
    assert {
        "forproducts",
        "productjobgo",
        "hireproproduct",
        "peersjobboard",
        "careerfedoroff",
        "jobinspb",
        "HRity",
        "budujobs",
        "projects_jobs",
    } <= names
    assert "foranalysts" not in names
    assert "jobospherechat" not in names
    assert "studyqa" not in names


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


def test_tbank_path_regex_and_slug_title():
    html = """
    <a href="/career/it/vacancy/moscow/timlid-produktovoj-analitiki-ekvajring/b8edbeb0-f104-4d16-ba68-87072deb62a9/">x</a>
    <a href="/career/service/vacancy/moscow/predstavitel/bc297685-1966-46ec-820a-b47f2a48492b/">y</a>
    <a href="/career/service/vacancy/moscow/operator-rannego-vzyskaniya/1aff2ffe-dd53-4b21-8cd9-1d63c8633f1a/">z</a>
    """
    drafts = parse_html_list(
        html,
        site_id="tbank",
        company="Т-Банк",
        list_url="https://www.tbank.ru/career/vacancies/it/",
        link_contains=["/vacancy/"],
        relevance=["produkt", "product", "lead", "timlid"],
        path_regex=r"/career/[^/]+/vacancy/[^/]+/[^/]+/[0-9a-f-]{8,}",
        path_exclude=["operator-rannego", "predstavitel"],
    )
    assert len(drafts) == 1
    assert drafts[0].external_id == "b8edbeb0-f104-4d16-ba68-87072deb62a9"
    assert "produkt" in drafts[0].title.lower()
    assert "откликнуться" not in drafts[0].title.lower()
    assert drafts[0].source == "career_tbank"


def test_geekjob_listing_keeps_product():
    from app.ingestion.jobs.geekjob_connector import (
        enrich_from_jsonld,
        parse_geekjob_listing,
    )

    html = """
    <li class="collection-item">
      <p class="truncate vacancy-name">
        <a href="/vacancy/aaaaaaaaaaaaaaaaaaaaaaaa" class="title">Senior Product Manager</a>
      </p>
      <p class="truncate company-name"><a href="/vacancy/aaaaaaaaaaaaaaaaaaaaaaaa">Acme</a></p>
      <span class="remote-label">remote</span>
    </li>
    <li class="collection-item">
      <p class="truncate vacancy-name">
        <a href="/vacancy/cccccccccccccccccccccccc" class="title">Sales manager</a>
      </p>
      <p class="truncate company-name"><a href="/vacancy/cccccccccccccccccccccccc">Y</a></p>
    </li>
    <li class="collection-item">
      <p class="truncate vacancy-name">
        <a href="/vacancy/bbbbbbbbbbbbbbbbbbbbbbbb" class="title">Junior Golang Developer</a>
      </p>
      <p class="truncate company-name"><a href="/vacancy/bbbbbbbbbbbbbbbbbbbbbbbb">X</a></p>
    </li>
    """
    drafts = parse_geekjob_listing(
        html, relevance=["product", "продукт", "cpo", "manager"], limit=40
    )
    assert len(drafts) == 1
    assert drafts[0].title == "Senior Product Manager"
    assert drafts[0].org == "Acme"
    assert drafts[0].remote is True
    assert drafts[0].source == "geekjob.ru"
    assert drafts[0].external_id == "aaaaaaaaaaaaaaaaaaaaaaaa"

    detail = """
    <script type="application/ld+json">
    {"@context":"https://schema.org/","@type":"JobPosting","title":"Senior Product Manager",
     "description":"Lead the roadmap and discovery.",
     "hiringOrganization":{"@type":"Organization","name":"Acme Corp"},
     "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Москва"}}}
    </script>
    """
    enrich_from_jsonld(detail, drafts[0])
    assert drafts[0].org == "Acme Corp"
    assert drafts[0].location == "Москва"
    assert "roadmap" in (drafts[0].description or "")


def test_career_yaml_lists_bigtech():
    cfg = load_career_config()
    ids = {s["id"] for s in cfg["sites"]}
    assert {"yandex", "sber", "tbank", "avito", "vk", "alfa", "ozon", "mts", "wildberries"} <= ids
    by_id = {s["id"]: s for s in cfg["sites"]}
    enabled = {s["id"] for s in cfg["sites"] if s.get("enabled", True)}
    assert "avito" in enabled and "vk" in enabled and "yandex" in enabled
    assert {"sber", "alfa", "mts", "wildberries", "tbank"} <= enabled
    assert by_id["alfa"]["kind"] == "alfa_api"
    assert by_id["wildberries"]["kind"] == "wb_api"
    assert by_id["sber"]["kind"] == "sber_api"
    assert by_id["mts"]["kind"] == "mts_api"
    assert "list_urls" in by_id["tbank"]
    assert "ozon" not in enabled


def test_parse_alfa_wb_sber_mts_payloads():
    """Офлайн-парсинг JSON-ответов волны A (без сети)."""
    import asyncio

    from app.ingestion.jobs import career_sites_connector as csc

    async def _run() -> None:
        class FakeResp:
            def __init__(self, data, status=200):
                self.status_code = status
                self._data = data

            def json(self):
                return self._data

        class FakeClient:
            def __init__(self, router):
                self.router = router

            async def get(self, url, params=None, headers=None):
                return FakeResp(self.router(url, params or {}))

        # Alfa
        alfa_client = FakeClient(
            lambda url, p: {
                "total": 1,
                "items": [
                    {
                        "id": "36532",
                        "name": "GenAI Product",
                        "slug": "/moskva/client-service/genai-product_36532",
                        "descriptionText": "Продукт на LLM",
                    }
                ],
            }
        )
        alfa = await csc._fetch_alfa(alfa_client, {"ssl_verify": True}, ["product"])
        assert len(alfa) == 1
        assert alfa[0].source == "career_alfa"
        assert alfa[0].external_id == "36532"
        assert "alfabank" in (alfa[0].url or "")

        # WB
        wb_client = FakeClient(
            lambda url, p: {
                "data": {
                    "items": [
                        {
                            "id": 99,
                            "name": "Product Lead",
                            "city_title": "Москва",
                            "direction_title": "Product",
                            "employment_types": [{"title": "Удалённо"}],
                        }
                    ]
                }
            }
        )
        wb = await csc._fetch_wb(wb_client, {}, ["product", "lead"])
        assert len(wb) == 1
        assert wb[0].source == "career_wb"
        assert wb[0].remote is True

        # Sber
        sber_client = FakeClient(
            lambda url, p: {
                "data": {
                    "total": 1,
                    "vacancies": [
                        {
                            "internalId": 4543221,
                            "title": "AI Developer",
                            "company": "Сбер",
                            "city": "Москва",
                            "introduction": "Python и product AI",
                        }
                    ],
                }
            }
        )
        sber = await csc._fetch_sber(sber_client, {}, ["product", "developer"])
        assert len(sber) == 1
        assert sber[0].source == "career_sber"

        # MTS
        mts_client = FakeClient(
            lambda url, p: {
                "data": [
                    {
                        "title": "Руководитель продукта",
                        "slug": "rukovoditel-produkta",
                        "documentId": "doc1",
                        "organization": {"title": "МТС"},
                        "region": {"title": "Москва"},
                        "categories": [{"title": "Product"}],
                        "workFormats": [{"title": "Гибрид"}],
                    }
                ],
                "meta": {"pagination": {"pageCount": 1}},
            }
        )
        mts = await csc._fetch_mts(mts_client, {}, ["продукт", "руководитель"])
        assert len(mts) == 1
        assert mts[0].source == "career_mts"
        assert mts[0].remote is True

    asyncio.run(_run())


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
    assert "geekjob.ru" in sources


def test_tg_http_proxy_reads_settings(monkeypatch):
    from app.ingestion.jobs import tg_proxy

    monkeypatch.setattr(tg_proxy.settings, "tg_http_proxy", "  socks5://u:p@h:1  ")
    assert tg_proxy.tg_http_proxy() == "socks5://u:p@h:1"
    monkeypatch.setattr(tg_proxy.settings, "tg_http_proxy", "")
    assert tg_proxy.tg_http_proxy() is None
