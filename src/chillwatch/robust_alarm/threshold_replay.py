from collections import defaultdict
from math import fsum


def find_threshold_agreement(groups, threshold):
    records = []
    for unit, samples in sorted(groups.items()):
        observed = [row for row in samples if row['score'] is not None and row['eligible']]
        if not observed:
            records.append({'unit':unit,'trigger_count':0,'peak_margin':None,'can_score':False,'legacy_mismatch':0})
            continue
        trigger_count = sum(row['score']>=threshold for row in observed)
        prior_mismatch = sum((row['score']>=threshold) != row['alarm'] for row in observed)
        upper_margin = max(row['score']-threshold for row in observed)
        records.append({'unit':unit,'trigger_count':trigger_count,'peak_margin':upper_margin,
                        'can_score':True,'legacy_mismatch':prior_mismatch})
    return records


def compare_operating_points(rows, thresholds=(.65,.75,.8,.9,.95)):
    values = tuple(thresholds)
    if not values or any(not 0<value<1 for value in values) or list(values)!=sorted(set(values)):
        raise ValueError('INVALID_REPLAY_THRESHOLDS')
    seen = set()
    groups = defaultdict(list)
    for row in sorted(rows,key=lambda item:(item['unit'],item['minute'])):
        identity = row['unit'],row['minute']
        if identity in seen:
            raise ValueError('AMBIGUOUS_THRESHOLD_EVIDENCE')
        seen.add(identity)
        groups[row['unit']].append(row)
    output = []
    for cut in values:
        cases = find_threshold_agreement(groups,cut)
        margins = [row['peak_margin'] for row in cases if row['peak_margin'] is not None]
        output.append({'threshold':cut,'new_alarms':sum(row['trigger_count'] for row in cases),
                       'unscorable_units':sum(not row['can_score'] for row in cases),
                       'changed_votes':sum(row['legacy_mismatch'] for row in cases),
                       'average_peak_margin':fsum(margins)/len(margins) if margins else None,
                       'equipment':cases})
    return output
