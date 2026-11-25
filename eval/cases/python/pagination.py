def paginate(items, page, per_page):
    start = page * per_page
    end = start + per_page
    return items[start:end]


def last_page(total, per_page):
    return total // per_page  # expect: bug


def window(values, size):
    return [values[i:i + size] for i in range(len(values) - size)]  # expect: bug


def average(values):
    return sum(values) / len(values)  # expect: bug
