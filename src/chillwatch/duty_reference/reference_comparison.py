from math import fsum, hypot


def compare_metric(first, second, overlap_cutoff):
    center_gap = abs(first['center']-second['center'])
    uncertainty = hypot(first['scale'],second['scale'])
    a0,a1 = first['minimum'],first['maximum']
    b0,b1 = second['minimum'],second['maximum']
    union = max(a1,b1)-min(a0,b0)
    overlap = max(0,min(a1,b1)-max(a0,b0))
    percentage = overlap/union if union else 1.0
    return {'center_gap':center_gap,'sigma_gap':center_gap/uncertainty,'range_overlap':percentage,
            'outside_matched_range':percentage<overlap_cutoff}


def compare_references(previous, current, *, drift_limit=1.8, overlap_cutoff=.25):
    if drift_limit <= 0 or not 0 <= overlap_cutoff <= 1:
        raise ValueError('INVALID_REFERENCE_DRIFT_LIMIT')
    old = {row['unit']:row for row in previous}
    new = {row['unit']:row for row in current}
    cases = []
    for unit in sorted(old.keys()|new.keys()):
        earlier,later=old.get(unit),new.get(unit)
        marker = None
        channels = {}
        if earlier is None or later is None:
            marker='NO_COMPARABLE_BASELINE'
        elif earlier['family'] != later['family'] or earlier['basis'] != later['basis']:
            marker='REFERENCE_COHORT_CHANGED'
        elif any(not ref[axis] for ref in (earlier,later) for axis in ('pressure','vibration')):
            marker='TOO_FEW_MATCHED_POINTS'
        else:
            for axis in ('pressure','vibration'):
                channels[axis]=compare_metric(earlier[axis],later[axis],overlap_cutoff)
            diverged = any(channel['outside_matched_range'] and channel['sigma_gap']>=drift_limit for channel in channels.values())
            marker='REFERENCE_DRIFT' if diverged else 'REFERENCE_STABLE'
        cases.append({'unit':unit,'status':marker,'channels':channels,
                      'comparison_mass':fsum(data['sigma_gap'] for data in channels.values()),
                      'previous_id':earlier['fit_id'] if earlier else None,'current_id':later['fit_id'] if later else None})
    return cases
