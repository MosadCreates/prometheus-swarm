export const mockMission = {
  id: 'mission-1',
  name: 'Titanic EDA + Training',
  project: 'Kaggle Titanic',
  status: 'running' as const,
  progress: 65,
  runtime: '12m 34s',
  started: '10:32 AM',
  eta: '~12 min',
  goal: 'Build a binary classification model to predict Titanic survival outcomes.',
  priority: 'High',
  description: 'Run EDA, train a LightGBM classifier, evaluate with cross-validation.',
};

export const mockAgents = [
  { id: 'scout', name: 'Scout', role: 'Perceiver', status: 'completed' as const, task: 'Dataset analysis complete', progress: 100, color: 'var(--color-agent-scout)' },
  { id: 'forge', name: 'Forge', role: 'Architect', status: 'completed' as const, task: 'Architecture selected', progress: 100, color: 'var(--color-agent-forge)' },
  { id: 'furnace', name: 'Furnace', role: 'Trainer', status: 'running' as const, task: 'Training LightGBM...', progress: 62, color: 'var(--color-agent-furnace)' },
  { id: 'dissect', name: 'Dissect', role: 'Debugger', status: 'waiting' as const, task: 'Standing by', progress: 0, color: 'var(--color-agent-dissect)' },
  { id: 'arbiter', name: 'Arbiter', role: 'Critic', status: 'waiting' as const, task: 'Awaiting results', progress: 0, color: 'var(--color-agent-arbiter)' },
  { id: 'harbor', name: 'Harbor', role: 'Deployer', status: 'waiting' as const, task: 'Awaiting deployment', progress: 0, color: 'var(--color-agent-harbor)' },
];

export const mockEvents = [
  { id: 'e1', agent: 'Scout', action: 'Parsed problem description', status: 'completed' as const, time: '10:32 AM', detail: 'Detected binary classification task, tabular modality, 891 rows × 12 columns.' },
  { id: 'e2', agent: 'Scout', action: 'EDA complete — missing values detected', status: 'completed' as const, time: '10:34 AM', detail: 'Age: 177 missing, Cabin: 687 missing, Embarked: 2 missing.' },
  { id: 'e3', agent: 'Scout', action: 'Wrote mission_brief.json', status: 'completed' as const, time: '10:36 AM', detail: 'Task: classification, Metric: auc_roc, Imbalance: class_weight.' },
  { id: 'e4', agent: 'Forge', action: 'Selected LightGBM architecture', status: 'completed' as const, time: '10:37 AM', detail: 'Model: LightGBM with class_weight, Optuna for hyperparameter tuning.' },
  { id: 'e5', agent: 'Forge', action: 'Generated training script', status: 'completed' as const, time: '10:39 AM', detail: 'Script: training_script_abc123.py with preprocessing pipeline.' },
  { id: 'e6', agent: 'Furnace', action: 'Launched training container', status: 'completed' as const, time: '10:40 AM', detail: 'Docker container started with 4 vCPU, 16 GB RAM.' },
  { id: 'e7', agent: 'Furnace', action: 'Epoch 1/50 — loss: 0.693', status: 'completed' as const, time: '10:42 AM', detail: 'Training loss: 0.693, Validation loss: 0.652' },
  { id: 'e8', agent: 'Furnace', action: 'Epoch 5/50 — loss: 0.421', status: 'completed' as const, time: '10:46 AM', detail: 'Training loss: 0.421, Validation loss: 0.389' },
  { id: 'e9', agent: 'Furnace', action: 'Epoch 10/50 — loss: 0.312', status: 'running' as const, time: '10:52 AM', detail: 'Training loss: 0.312, Validation loss: 0.298, Best AUC: 0.87' },
  { id: 'e10', agent: 'Furnace', action: 'Epoch 15/50 — loss: 0.245', status: 'running' as const, time: '10:58 AM', detail: 'Training loss: 0.245, Validation loss: 0.231' },
];

export const mockTimeline = [
  { label: 'Queued', completed: true },
  { label: 'Planning', completed: true },
  { label: 'Research', completed: true },
  { label: 'Development', completed: true },
  { label: 'Training', completed: false, active: true },
  { label: 'Validation', completed: false },
  { label: 'Deployment', completed: false },
  { label: 'Completed', completed: false },
];

export const mockArtifacts = [
  { name: 'training_script.py', type: 'code' as const, size: '4.2 KB' },
  { name: 'mission_brief.json', type: 'json' as const, size: '1.1 KB' },
  { name: 'features.py', type: 'code' as const, size: '2.8 KB' },
  { name: 'preprocessing.py', type: 'code' as const, size: '3.1 KB' },
];

export const mockResources = {
  cpu: 45,
  gpu: 0,
  memory: 62,
  storage: 18,
};

export const agentStatusColor: Record<string, string> = {
  waiting: 'var(--color-text-muted)',
  running: 'var(--color-primary)',
  completed: 'var(--color-success)',
  failed: 'var(--color-error)',
  thinking: 'var(--color-warning)',
};
