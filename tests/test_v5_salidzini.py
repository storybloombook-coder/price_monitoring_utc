"""Regression cases from visible Salidzini DOM captured on 2026-08-31."""
from pathlib import Path
import pytest
from price_monitor_v5.offers import parse_page, candidate_links

FIXTURES = Path(__file__).parent / 'fixtures'
URL = 'https://www.salidzini.lv/cena?q=TCL+115RM9L'


@pytest.mark.parametrize('model,sellers,prices,stock', [
    ('115RM9L', ['euronics.lv', 'signe.lv', 'bigbox.lv'], [12999, 12999, 12999], 'IN_STOCK'),
    ('25G64', ['lmt.lv', 'bite.lv'], [199, 208.8], 'UNKNOWN'),
])
def test_live_dom_offers_exclude_geedo_and_do_not_mix_country_brands(model, sellers, prices, stock):
    html = (FIXTURES / f'salidzini-{model.lower()}-cards.html').read_text(encoding='utf-8')
    url = 'https://www.salidzini.lv/cena?q=TCL+' + model
    parsed = parse_page('salidzini', model, html, url)
    assert [o['store'] for o in parsed['offers']] == sellers
    assert [o['price_eur'] for o in parsed['offers']] == prices
    assert {o['availability'] for o in parsed['offers']} == {stock}
    assert all(o['seller_key'] is None for o in parsed['offers'])  # .lv is not .ee/.lt.
    assert all(o['url'] == url for o in parsed['offers'])  # Never expose/follow click.php.
    assert parsed['rejected'] == 0 and not parsed['not_found']


def modern_card(href='/click.php?itemid=123', stock='Noliktavā: 1', price='199,00', title='TCL 115RM9L'):
    return f'''<div class="item_box_main"><div class="item_box_sub">
        <div class="item_shop_name">seller.lv</div>
        <a class="item_link" href="{href}"><h2 class="item_name">{title}</h2>
        <div class="item_price"><span>{price}</span>&nbsp;€</div></a>
        <div class="item_delivery_stock_frame_new"><i title="{stock}"></i><i title="Piegāde: 5 darba dienas 20€"></i>5d 20€</div>
        </div></div>'''


@pytest.mark.parametrize('stock,expected', [('Noliktavā: 0','OUT_OF_STOCK'),
    ('Noliktavā: 50+','IN_STOCK'), ('', 'UNKNOWN')])
def test_stock_count_not_shipping_or_stock_quantity_as_price(stock, expected):
    offer = parse_page('salidzini','115RM9L',modern_card(stock=stock),URL)['offers'][0]
    assert offer['availability'] == expected and offer['price_eur'] == 199


@pytest.mark.parametrize('href', ['/click.php', 'https://shop.test/123', '/cena?q=115RM9L'])
def test_unknown_card_links_are_not_trusted(href):
    parsed = parse_page('salidzini','115RM9L',modern_card(href=href),URL)
    assert not parsed['offers'] and not parsed['not_found'] and parsed['rejected'] == 1


def test_ambiguous_price_requires_review():
    parsed = parse_page('salidzini','115RM9L',modern_card(price='199,00 EUR 5,00'),URL)
    assert not parsed['offers'] and parsed['rejected'] == 1


def test_shortened_search_suggests_real_cards_only_without_accepting_variant_price():
    html = modern_card(title='TCL 115RM9X') + modern_card(href='https://geedo.lv/?q=115RM9', title='TCL 115RM9Y')
    assert not parse_page('salidzini','115RM9L',html,URL)['offers']
    candidates = candidate_links('115RM9', html, URL, 'salidzini')
    assert candidates == [{'title':'TCL 115RM9X','url':URL,'query':'115RM9'}]


def test_only_geedo_does_not_prove_not_found():
    parsed = parse_page('salidzini','115RM9L',modern_card(href='https://geedo.lv/?q=115RM9L'),URL)
    assert not parsed['offers'] and not parsed['not_found']
