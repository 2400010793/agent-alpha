#!/usr/bin/env bash
cd /mnt/lustre3/home/gaozh/my-paper-digest-new2
nohup bash deploy/bin/run_three_ai_hourly_once.sh > logs/three_ai_hourly_once.nohup.log 2>&1 &
