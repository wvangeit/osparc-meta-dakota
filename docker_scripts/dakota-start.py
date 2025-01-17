import contextlib
import logging
import os
import pathlib as pl
import shutil
import sys
import time
import uuid

import dakota.environment as dakenv
import numpy as np
from osparc_filecomms import handshakers

logging.basicConfig(
    level=logging.INFO, format="[%(filename)s:%(lineno)d] %(message)s"
)
logger = logging.getLogger(__name__)

sys.path.append(str((pl.Path(__file__) / "tools").resolve().parent))
print(
    "Added to python search python: "
    f"{str(pl.Path(__file__).resolve().parent)}"
)

import tools.maps  # NOQA


NOISE_MUS = [0.0, 0.0]
NOISE_SIGMAS = [5.0, 10.0]

POLLING_TIME = 0.1


def main():
    dakota_service = DakotaService()
    dakota_service.start()


class DakotaService:
    def __init__(self):
        self.uuid = uuid.uuid4()
        self.caller_uuid = None
        self.map_uuid = None

        self.input_dir_path = pl.Path(os.environ["DY_SIDECAR_PATH_INPUTS"])
        self.input0_dir_path = self.input_dir_path / "input_0"
        self.input1_dir_path = self.input_dir_path / "input_1"

        self.output_dir_path = pl.Path(os.environ["DY_SIDECAR_PATH_OUTPUTS"])
        self.output0_dir_path = self.output_dir_path / "output_0"
        self.output1_dir_path = self.output_dir_path / "output_1"

        self.dakota_conf_path = self.input0_dir_path / "dakota.in"

        self.map_caller_file_path = self.output1_dir_path / "input_tasks.json"
        self.map_reply_file_path = self.input1_dir_path / "output_tasks.json"

        self.caller_handshaker = handshakers.FileHandshaker(
            self.uuid,
            self.input0_dir_path,
            self.output0_dir_path,
            is_initiator=True,
        )

        self.clean_output(self.output0_dir_path)

    def clean_output(self, dir_path):
        for item in dir_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    def start(self):
        self.map_object = tools.maps.oSparcFileMap(
            self.map_reply_file_path.resolve(),
            self.map_caller_file_path.resolve(),
        )

        self.caller_uuid = self.caller_handshaker.shake()

        while not self.dakota_conf_path.exists():
            time.sleep(POLLING_TIME)
        dakota_conf = self.dakota_conf_path.read_text()

        self.start_dakota(dakota_conf, self.output0_dir_path)

    def model_callback(self, dak_inputs):
        # print(f"evaluating: {dak_inputs}")
        #
        param_sets = [
            {
                label: value
                for label, value in zip(
                    dak_input["cv_labels"], dak_input["cv"]
                )
            }
            for dak_input in dak_inputs
        ]
        all_response_labels = [
            dak_input["function_labels"] for dak_input in dak_inputs
        ]
        obj_sets = self.map_object.evaluate(param_sets)
        dak_outputs = [
            {
                "fns": [
                    obj_set[response_label]
                    for response_label in response_labels
                ]
            }
            for obj_set, response_labels in zip(obj_sets, all_response_labels)
        ]
        # print(f"output: {dak_outputs}")
        return dak_outputs

    def model(self, input, mus=NOISE_MUS, sigmas=NOISE_SIGMAS):
        x0, x1, x2 = input
        noise0 = np.random.normal(mus[0], sigmas[0])
        noise1 = np.random.normal(mus[1], sigmas[1])
        y0 = x0 + x1 + noise0
        y1 = x2 + noise1
        return y0, y1

    def start_dakota(self, dakota_conf, output_dir):
        with working_directory(output_dir):
            callbacks = {"model": self.model_callback}
            study = dakenv.study(callbacks=callbacks, input_string=dakota_conf)
            study.execute()


@contextlib.contextmanager
def working_directory(path):
    """Changes working directory and returns to previous on exit."""
    prev_cwd = pl.Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev_cwd)


if __name__ == "__main__":
    main()
