from collections import Counter, defaultdict


def missed_boundaries(minutes, *, period, begin, end):
    covered = defaultdict(list)
    unexpected = []
    for minute in minutes:
        if not begin <= minute < end:
            unexpected.append(minute)
            continue
        slot = begin + ((minute - begin) // period) * period
        covered[slot].append(minute)
    gaps = []
    previous_missing = None
    for slot in range(begin, end, period):
        if slot not in covered:
            if previous_missing is not None and gaps[previous_missing]['end'] == slot:
                gaps[previous_missing]['end'] = min(slot + period, end)
            else:
                previous_missing = len(gaps)
                gaps.append({'start': slot, 'end': min(slot + period, end)})
    return covered, gaps, sorted(unexpected)


def audit_sampling(rows, *, period=10, begin=550, end=590):
    if type(period) is not int or period < 1 or end <= begin:
        raise ValueError('INVALID_SCAN_CADENCE')
    minutes_by_unit = defaultdict(list)
    rejections = defaultdict(Counter)
    for row in rows:
        unit = row['unit']
        if row['status'] == 'accepted':
            minutes_by_unit[unit].append(row['minute'])
        else:
            rejections[unit][row['reason']] += 1
    audit = []
    for unit in sorted(minutes_by_unit.keys() | rejections.keys()):
        windows, missing, unexpected = missed_boundaries(minutes_by_unit[unit],period=period,begin=begin,end=end)
        double_capture = sorted(start for start, matches in windows.items() if len(matches)>1)
        counts = sum((gap['end']-gap['start']+period-1)//period for gap in missing)
        total = len(windows)+counts
        audit.append({
            'unit':unit,
            'expected_slots':total,
            'observed_slots':len(windows),
            'observed_ratio':len(windows)/total,
            'missing_intervals':missing,
            'double_capture':double_capture,
            'outside_shift':unexpected,
            'rejected_reasons':dict(rejections[unit]),
        })
    return audit
