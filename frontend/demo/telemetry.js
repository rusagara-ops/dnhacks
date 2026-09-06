/* Resolve worker history by persistent device identity. Modern registrations
   reuse their worker ID on restart. Legacy rows without a device ID stay separate:
   names and hostnames are labels, not evidence that two records are one machine. */
window.Telemetry = (() => {
  const TASK_TYPES = ['summarization', 'document-qa', 'information-extraction', 'coding-assistance'];
  const LABELS = {
    'summarization': 'Summarize',
    'document-qa': 'Document Q&A',
    'information-extraction': 'Extract',
    'coding-assistance': 'Coding'
  };

  const machineKey = worker => worker?.device_id ? `device:${worker.device_id}` : worker?.id ? `worker:${worker.id}` : '';

  function blank(key, name) {
    return {
      key, name, hostnames: new Set(), workerIds: new Set(), models: new Set(),
      completedTasks: 0, completedInputs: 0, executionMsTotal: 0,
      activeTasks: [], recentTasks: [], byType: new Map(),
      status: 'OFFLINE', online: false, lastTask: null
    };
  }

  /* activity: /api/activity. workers: /api/workers?include_history=true, which is
     what resolves worker IDs that no longer appear in the live listing. */
  function machines(activity, workers) {
    const byId = new Map((workers || []).map(worker => [worker.id, worker]));
    const groups = new Map();

    const group = (workerId, fallbackName, taskId) => {
      const worker = byId.get(workerId);
      const key = machineKey(worker) || (workerId ? `worker:${workerId}` : `task:${taskId}`);
      const name = worker?.name || fallbackName || `Unknown worker ${String(workerId || taskId).slice(0, 8)}`;
      if (!groups.has(key)) groups.set(key, blank(key, name));
      const entry = groups.get(key);
      if (workerId) entry.workerIds.add(workerId);
      if (worker) {
        if (worker.hostname) entry.hostnames.add(worker.hostname);
        for (const model of worker.models?.length ? worker.models : worker.model_id ? [worker] : []) {
          if (model.model_id) entry.models.add(model.model_id);
        }
        // A machine is online when any of its registrations is.
        if (['AVAILABLE', 'BUSY'].includes(worker.status)) { entry.online = true; entry.status = worker.status; }
      }
      return entry;
    };

    for (const metric of activity?.worker_metrics || []) {
      const entry = group(metric.worker_id);
      entry.completedTasks += metric.completed_tasks || 0;
      entry.completedInputs += metric.completed_inputs || 0;
      entry.executionMsTotal += (metric.average_execution_ms || 0) * (metric.completed_tasks || 0);
    }
    for (const task of activity?.active_tasks || []) {
      const entry = group(task.worker_id, task.worker_name, task.task_id);
      entry.activeTasks.push(task);
    }
    for (const task of activity?.recent_tasks || []) {
      if (!task.worker_id && !task.worker_name) continue;
      const entry = group(task.worker_id, task.worker_name, task.task_id);
      entry.recentTasks.push(task);
      if (!entry.lastTask) entry.lastTask = task;
    }
    /* Per-task-type totals when the coordinator reports them; otherwise the recent
       window is all that exists, and the caller labels the chart accordingly. */
    const reported = activity?.worker_task_types;
    if (Array.isArray(reported)) {
      for (const row of reported) {
        const entry = group(row.worker_id);
        entry.byType.set(row.task_type, (entry.byType.get(row.task_type) || 0) + (row.completed_tasks || 0));
      }
    } else {
      for (const task of activity?.recent_tasks || []) {
        if (task.status !== 'COMPLETED' || (!task.worker_id && !task.worker_name)) continue;
        const entry = group(task.worker_id, task.worker_name, task.task_id);
        entry.byType.set(task.task_type, (entry.byType.get(task.task_type) || 0) + 1);
      }
    }

    const nameCounts = new Map();
    for (const entry of groups.values()) nameCounts.set(entry.name, (nameCounts.get(entry.name) || 0) + 1);
    return [...groups.values()]
      .map(entry => ({
        ...entry,
        name: nameCounts.get(entry.name) > 1 ? `${entry.name} · ${entry.key.split(':')[1].slice(0, 8)}` : entry.name,
        hostnames: [...entry.hostnames],
        workerIds: [...entry.workerIds],
        models: [...entry.models],
        registrations: entry.workerIds.size,
        averageExecutionMs: entry.completedTasks ? entry.executionMsTotal / entry.completedTasks : null
      }))
      .sort((a, b) => b.completedTasks - a.completedTasks || a.name.localeCompare(b.name));
  }

  // True when per-task-type counts cover all history rather than the recent window.
  const hasFullTypeHistory = activity => Array.isArray(activity?.worker_task_types);

  function typeTotals(machines) {
    const totals = new Map();
    for (const machine of machines) {
      for (const [type, count] of machine.byType) totals.set(type, (totals.get(type) || 0) + count);
    }
    return [...totals.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([type, count]) => ({type, label: LABELS[type] || type, count}));
  }

  function summary(activity) {
    const counts = activity?.task_counts || {};
    return {
      queued: counts.QUEUED || 0,
      active: (counts.RUNNING || 0) + (counts.ASSIGNED || 0),
      completed: counts.COMPLETED || 0,
      failed: counts.FAILED || 0,
      retries: activity?.retries || 0
    };
  }

  return {machines, typeTotals, summary, hasFullTypeHistory, TASK_TYPES, LABELS};
})();
