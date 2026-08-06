import torch

print("PyTorch版本：", torch.__version__)
print("CUDA是否可用：", torch.cuda.is_available())
print("GPU型号：", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "无GPU")