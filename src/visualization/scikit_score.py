# TODO: shouldn't I split this task in 2: scores and confusion matrix?
# or train and test?

import luigi
import matplotlib.pyplot as plt
import pandas as pd
import pickle
import mlflow
import seaborn as sns
from sklearn import metrics
import yaml

from src.data.external_test_set import ExternalTestSet
from src.data.external_train_set import ExternalTrainSet
from src.data.external_label_titles import ExternalLabelTitles
from src.models.baseline_logistic_regression import TrainBaselineLogisticRegression
from src.utils.params_to_filename import params_to_filename
from src.utils.extract_x_y import extract_x_and_y


class ScikitScore(luigi.Task):
    model_name = luigi.Parameter(
        default='logistic-regression',
        description='model name (e.g. logistic-regression)'
    )
    model_params = luigi.DictParameter(
        default={},
        description='model params'
    )

    def output(self):
        filename = params_to_filename({
            'model': self.model_name,
            **self.model_params
        })
        return {
            'score': luigi.LocalTarget(f'reports/scores/{filename}.yaml'),
            'train_cm': luigi.LocalTarget(f'reports/figures/confusion_matrices/{filename}_train.png'),
            'test_cm': luigi.LocalTarget(f'reports/figures/confusion_matrices/{filename}_test.png'),
        }

    def requires(self):
        return (
            TrainBaselineLogisticRegression(**self.model_params),
            ExternalLabelTitles(),
            ExternalTestSet(),
            ExternalTrainSet(),
        )

    def _score(self, y_true, y_pred):
        return {
            'accuracy': float(metrics.accuracy_score(y_true, y_pred)),
            'cohen_kappa': float(metrics.cohen_kappa_score(y_true, y_pred)),
            'f1': float(metrics.f1_score(y_true, y_pred, average='macro')),
            'precision': float(metrics.precision_score(y_true, y_pred, average='macro')),
            'recall': float(metrics.recall_score(y_true, y_pred, average='macro')),
        }

    def _save_confusion_matrix(self, y_true, y_pred, input_file, fontsize=14):
        with self.input()[1].open('r') as f:
            label_titles = yaml.load(f)

        train_cm = metrics.confusion_matrix(y_true, y_pred,
                                            range(len(label_titles)))
        df_cm = pd.DataFrame(
            train_cm, index=label_titles, columns=label_titles,
        )
        fig = plt.figure(figsize=(10, 7))
        heatmap = sns.heatmap(df_cm, annot=True, fmt="d")
        heatmap.yaxis.set_ticklabels(heatmap.yaxis.get_ticklabels(), rotation=0, ha='right', fontsize=fontsize)
        heatmap.xaxis.set_ticklabels(heatmap.xaxis.get_ticklabels(), rotation=45, ha='right', fontsize=fontsize)
        plt.ylabel('True label')
        plt.xlabel('Predicted label')
        input_file.makedirs()
        plt.savefig(input_file.path, dpi=150)
        return input_file.path

    def run(self):
        model = pickle.load(self.input()[0].open('r'))
        X_test, y_test = extract_x_and_y(self.input()[2])
        X_train, y_train = extract_x_and_y(self.input()[3])
        y_test_pred = model.predict(X_test)
        y_train_pred = model.predict(X_train)

        scores = {
            'test': self._score(y_test, y_test_pred),
            'train': self._score(y_train, y_train_pred),
        }

        with self.output()['score'].open('w') as f:
            yaml.dump(scores, f, default_flow_style=False)

        mlflow.log_param('model_name', self.model_name)
        for (score_name_train, score_value_train), (score_name_test, score_value_test) \
                in zip(scores['train'].items(), scores['test'].items()):
            # Names may only contain alphanumerics, underscores (_),
            #  dashes (-), periods (.), spaces ( ), and slashes (/).
            mlflow.log_metric(f'{score_name_train} train', score_value_train)
            mlflow.log_metric(f'{score_name_test} test', score_value_test)

        test_cm_path = self._save_confusion_matrix(y_test, y_test_pred, self.output()['test_cm'])
        train_cm_path = self._save_confusion_matrix(y_train, y_train_pred, self.output()['train_cm'])

        mlflow.log_artifact(test_cm_path, 'confusion_matrices/test')
        mlflow.log_artifact(train_cm_path, 'confusion_matrices/train')

        print(f'Model saved in run {mlflow.active_run().info.run_uuid}')


if __name__ == '__main__':
    with mlflow.start_run():
        luigi.run(main_task_cls=ScikitScore)
