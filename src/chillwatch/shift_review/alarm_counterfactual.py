from collections import Counter
from math import fsum

from .algorithm import verified_observations
from .contracts import parse


def wilson(successes, total, critical=1.96):
    if total == 0:
        return None
    ratio = successes/total
    z2 = critical**2
    denominator = 1+z2/total
    center = (ratio+z2/(2*total))/denominator
    radius = critical*((ratio*(1-ratio)/total+z2/(4*total**2))**.5)/denominator
    return [max(0,center-radius),min(1,center+radius)]


def inspection_counterfactual(rows, *, as_of, false_alarm_cost=25, missed_cost=220, thresholds=(.35,.5,.65,.8,.95)):
    if min(false_alarm_cost,missed_cost)<0 or len(thresholds)<2 or not all(0<cut<1 for cut in thresholds):
        raise ValueError('INVALID_INSPECTION_REPLAY_CONFIG')
    data,exclusions = verified_observations([parse(row) for row in rows],as_of)
    proposals = []
    fault_count = sum(row.confirmed for row in data)
    for cut in sorted(set(thresholds)):
        bins = Counter()
        for row in data:
            if row.score >= cut:
                bins['caught' if row.confirmed else 'avoidable_check'] += 1
            else:
                bins['undetected' if row.confirmed else 'cleared'] += 1
        total = fsum((bins['avoidable_check']*false_alarm_cost,bins['undetected']*missed_cost))
        proposals.append({'threshold':cut,'checked':bins['caught']+bins['avoidable_check'],
                          'avoidable_checks':bins['avoidable_check'],'undetected_faults':bins['undetected'],
                          'recall_interval':wilson(bins['caught'],fault_count),
                          'estimated_cost':total if data else None})
    best = min(proposals,key=lambda row:(row['estimated_cost'],row['undetected_faults'],row['threshold'])) if data else None
    return {'closed_samples':len(data),'closed_faults':fault_count,'excluded':exclusions,'proposals':proposals,
            'historical_preferred_threshold':best['threshold'] if best else None}
