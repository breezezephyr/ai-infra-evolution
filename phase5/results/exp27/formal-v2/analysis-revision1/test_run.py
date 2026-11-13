"""CPU environment probes only; never start the supervisor or access a GPU."""
import importlib.util,pathlib
from unittest.mock import patch
D=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('exp27_run_probe',D/'run.py');run=importlib.util.module_from_spec(spec);spec.loader.exec_module(run)

def test_gpu_query_resolves_linux_path():
 with patch.object(run.shutil,'which',return_value='/usr/bin/nvidia-smi'),patch.object(run.subprocess,'check_output',return_value='device, 0 MiB\n') as call:
  assert run.gpu()=='device, 0 MiB'
  assert call.call_args.args[0][0]=='/usr/bin/nvidia-smi'
