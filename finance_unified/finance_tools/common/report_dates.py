def date_range(values):
    dates = sorted({str(value)[:10] for value in values if value})
    if not dates:
        return ''
    return dates[0] if dates[0] == dates[-1] else f'{dates[0]}～{dates[-1]}'
