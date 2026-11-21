#!/bin/sh
set -e
# 宿主机挂载的 /app/data 若还没有库，用镜像内的种子数据初始化，避免空目录把内置用例盖住。
if [ ! -f /app/data/platform.db ]; then
  mkdir -p /app/data
  if [ -d /app/data-seed ]; then
    cp -a /app/data-seed/. /app/data/
  fi
fi
exec "$@"
