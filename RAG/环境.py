import torch
print(torch.__version__)          # 查看版本
print(torch.version.cuda)         # 如果是 CPU 版，这里会是 None
print(torch.backends.cudnn.version())  # 同样，CPU 版会报错或 None