# QRM-Lite Beta-1 Q0/Q1/Q2 train

## Q0_COARSE_ONLY
- val skill acc: 1.000 (macro-F1 1.000)
- coarse final: `{'epoch': 299, 'loss': 0.003829903804550756, 'skill_acc': 1.0}`

## Q1_COARSE_MLP_RESIDUAL
- val skill acc: 1.000 (macro-F1 1.000)
- coarse final: `{'epoch': 299, 'loss': 0.003829903804550756, 'skill_acc': 1.0}`
- mlp beats zero residual: False
- residual errors: `{'l1': 0.008227692838636494, 'l2': 0.014501491862685857, 'translation_l1': 0.009431581019125277}`

## Q2_COARSE_MLP_FAILURE_CONTEXT
- val skill acc: 1.000 (macro-F1 1.000)
- coarse final: `{'epoch': 299, 'loss': 0.0016241972004723151, 'skill_acc': 1.0}`
- mlp beats zero residual: False
- residual errors: `{'l1': 0.007045738204402632, 'l2': 0.011648744148454548, 'translation_l1': 0.008096389129680515}`

Majority baseline acc: 0.833
Flow: IMPLEMENTED_NOT_SELECTED
