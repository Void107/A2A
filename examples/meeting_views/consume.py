"""Local task consumers; no network or external side effects."""
from datetime import date


def consume(data, view_id):
    if view_id not in {'internal-project', 'external-collaboration'}:
        raise ValueError('UNKNOWN_CONSUMER')
    internal = view_id == 'internal-project'
    tasks = []
    for item in data['action_items']:
        date.fromisoformat(item['due_date'])
        if not internal and any(k in item for k in ('owner_name', 'owner_email')):
            raise ValueError('FORBIDDEN_IDENTITY_FIELD')
        assignee = item['owner_email'] if internal else None
        if internal and (not isinstance(assignee, str) or '@' not in assignee):
            raise ValueError('ASSIGNEE_REQUIRED')
        tasks.append({'item_id': item['item_id'], 'task': item['task'],
                      'due_date': item['due_date'], 'assignee': assignee,
                      'assignment_state': 'assigned' if internal else 'unassigned'})
    return tasks
