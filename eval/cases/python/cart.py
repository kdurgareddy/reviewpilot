import logging

log = logging.getLogger(__name__)


def add_item(item, cart=[]):  # expect: bug
    cart.append(item)
    return cart


def add_item_safe(item, cart=None):
    cart = cart if cart is not None else []
    cart.append(item)
    return cart


def apply_discount(total, code):
    try:
        rate = lookup_rate(code)
    except:  # expect: bug
        rate = 0
    return total * (1 - rate)


def charge(card, amount):
    try:
        gateway_charge(card, amount)
    except Exception:  # expect: bug
        pass


def refund(card, amount):
    try:
        gateway_refund(card, amount)
    except TimeoutError:
        log.warning("refund timed out, will retry")
        raise


def is_empty(cart):
    return cart == None  # expect: bug


def is_vip(level):
    return level is "gold"  # expect: bug


def lookup_rate(code):
    return {"SAVE10": 0.1}.get(code, 0)


def gateway_charge(card, amount):
    ...


def gateway_refund(card, amount):
    ...
