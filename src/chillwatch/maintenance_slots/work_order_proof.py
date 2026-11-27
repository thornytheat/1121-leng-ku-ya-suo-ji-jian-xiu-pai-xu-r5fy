from collections import defaultdict
from itertools import combinations


def pair_conflicts(spans, scope):
    defects = []
    for key in sorted(spans):
        intervals = sorted(spans[key])
        for (begin,end,unit),(next_begin,next_end,next_unit) in combinations(intervals,2):
            if next_begin >= end:
                continue
            defects.append({'reason':scope,'identity':str(key),'units':[unit,next_unit],
                            'overlap':[next_begin,min(end,next_end)]})
    return defects


def reconcile_schedule(work, *, start=600, end=735, crew_count=2):
    groups = defaultdict(list)
    rack_windows = defaultdict(list)
    errors = []
    scheduled = set()
    blocks = 0
    for row in work:
        if row['state'] != '已排检':
            if any(row[name] is not None for name in ('crew','start','end')):
                errors.append({'unit':row['unit'],'reason':'UNPAID_SLOT_PRESENT'})
            continue
        unit,crew,begin,finish = (row[name] for name in ('unit','crew','start','end'))
        if unit in scheduled:
            errors.append({'unit':unit,'reason':'DUPLICATE_MAINTENANCE'})
        scheduled.add(unit)
        if type(crew) is not int or not 1<=crew<=crew_count or type(begin) is not int or type(finish) is not int:
            errors.append({'unit':unit,'reason':'MALFORMED_WORK_SLOT'})
            continue
        if not max(start,row['allowed_start'])<=begin<finish<=min(end,row['allowed_end']) or finish-begin!=row['runtime']:
            errors.append({'unit':unit,'reason':'OUTSIDE_APPROVED_WINDOW'})
        if not row['has_backup']:
            errors.append({'unit':unit,'reason':'MISSING_STANDBY_MACHINE'})
        groups[crew].append((begin,finish,unit))
        rack_windows[row['rack']].append((begin,finish,unit))
        blocks += max(0,finish-begin)
    errors.extend(pair_conflicts(groups,'CREW_DOUBLE_BOOKED'))
    errors.extend(pair_conflicts(rack_windows,'RACK_REDUNDANCY_BROKEN'))
    return {'scheduled':len(scheduled),'total_crew_minutes':blocks,'crew_minutes':{
            str(crew):sum(max(0,finish-begin) for begin,finish,_ in windows) for crew,windows in sorted(groups.items())},
            'defects':errors,'verified':not errors}
