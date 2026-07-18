# QRM-Lite Beta-1 Q0/Q1/Q2 train

## Q0_COARSE_ONLY
- val skill acc: 0.700 (macro-F1 0.577)
- coarse final: `{'epoch': 199, 'loss': 0.02608474227348615, 'skill_acc': 0.8245614035087719}`

## Q1_COARSE_MLP_RESIDUAL
- val skill acc: 0.700 (macro-F1 0.577)
- coarse final: `{'epoch': 199, 'loss': 0.02608474227348615, 'skill_acc': 0.8245614035087719}`
- mlp beats zero residual: True
- residual errors: `{'l1': 0.0390814543096541, 'l2': 0.06313232311042899, 'translation_l1': 0.02306804841901553}`

## Q2_COARSE_MLP_FAILURE_CONTEXT
- val skill acc: 0.700 (macro-F1 0.576)
- coarse final: `{'epoch': 199, 'loss': 0.024739671971436488, 'skill_acc': 0.8491228070175438}`
- mlp beats zero residual: True
- residual errors: `{'l1': 0.042027605058263744, 'l2': 0.06541357139559588, 'translation_l1': 0.022884641382962034}`

Majority baseline acc: 0.140
Flow: IMPLEMENTED_NOT_SELECTED
