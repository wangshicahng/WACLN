import os
import sys
import time
import glob
import torch
import random
import logging
import numpy as np
from tqdm import tqdm
import torch.nn as nn
import torch.utils.data
from common.utils import *
import torch.optim as optim
from common.camera import *
import common.loss as eval_loss
from common.arguments import parse_args
from common.load_data_hm36 import Fusion
from common.h36m_dataset import Human36mDataset
args = parse_args()
os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
exec('from model.' + args.model + ' import Model')
def train(dataloader, model, optimizer, epoch):
    model.train()
    loss_all = {'loss': AccumLoss()}
    total_time = 0
    total_frames = 0
    pbar = tqdm(dataloader, dynamic_ncols=True)
    for i, data in enumerate(pbar):
        start_time = time.time()
        batch_cam, gt_3D, input_2D, input_2D_GT, action, subject, cam_ind = data
        input_2D, input_2D_GT, gt_3D, batch_cam = input_2D.cuda(), input_2D_GT.cuda(), gt_3D.cuda(), batch_cam.cuda()
        output_3D, index = model(input_2D)
        out_target = gt_3D.clone()
        out_target[:, :, args.root_joint] = 0
        batch_ind = torch.arange(out_target.shape[0], device=out_target.device).unsqueeze(-1)
        out_target = out_target[batch_ind, index, :]
        loss = eval_loss.mpjpe(output_3D, out_target)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        N = input_2D.shape[0]
        loss_all['loss'].update(loss.detach().cpu().numpy() * N, N)
        batch_time = time.time() - start_time
        total_time += batch_time
        total_frames += input_2D.shape[0]
        fps = total_frames / total_time
        avg_fps = total_frames / total_time
        pbar.set_postfix(FPS=f"{fps:.2f}", avg_fps=f"{avg_fps:.2f}")
    return loss_all['loss'].avg


def test(actions, dataloader, model):
    model.eval()
    action_error = define_error_list(actions)
    joints_left = [4, 5, 6, 11, 12, 13]
    joints_right = [1, 2, 3, 14, 15, 16]
    total_time = 0
    total_frames = 0
    pbar = tqdm(dataloader, dynamic_ncols=True)
    for i, data in enumerate(pbar):
        start_time = time.time()
        batch_cam, gt_3D, input_2D, input_2D_GT, action, subject, cam_ind = data
        input_2D, input_2D_GT, gt_3D, batch_cam = input_2D.cuda(), input_2D_GT.cuda(), gt_3D.cuda(), batch_cam.cuda()
        output_3D_non_flip, index_non_flip = model(input_2D[:, 0])
        output_3D_flip, index_flip = model(input_2D[:, 1], index_non_flip)
        output_3D_flip[:, :, :, 0] *= -1
        output_3D_flip[:, :, joints_left + joints_right, :] = output_3D_flip[:, :, joints_right + joints_left, :]
        output_3D = (output_3D_non_flip + output_3D_flip) / 2
        pad_exist, index_center = torch.where(index_non_flip == args.pad)
        index_center = index_center.unsqueeze(1)
        batch_ind = torch.arange(output_3D.shape[0], device=output_3D.device).unsqueeze(-1)
        output_3D = output_3D[batch_ind, index_center]
        output_3D[:, :, args.root_joint] = 0
        out_target = gt_3D.clone()
        out_target = gt_3D[:, args.pad].unsqueeze(1)
        out_target[:, :, args.root_joint] = 0
        action_error = test_calculation(output_3D, out_target, action, action_error, args.dataset, subject)
        batch_time = time.time() - start_time
        total_time += batch_time
        total_frames += input_2D.shape[0]
        fps = total_frames / total_time
        avg_fps = total_frames / total_time
        pbar.set_postfix(FPS=f"{fps:.2f}", avg_fps=f"{avg_fps:.2f}")

    p1, p2 = print_error(args.dataset, action_error, 1)

    return p1, p2


if __name__ == '__main__':
    seed = 1
    random.seed(seed)
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    dataset_path = args.root_path + 'data_3d_' + args.dataset + '.npz'
    dataset = Human36mDataset(dataset_path, args)
    actions = define_actions(args.actions)
    if args.train:
        train_data = Fusion(args, dataset, args.root_path, train=True)
        train_dataloader = torch.utils.data.DataLoader(train_data, batch_size=args.batch_size,
                                                       shuffle=True, num_workers=int(args.workers), pin_memory=True)
    test_data = Fusion(args, dataset, args.root_path, train=False)
    test_dataloader = torch.utils.data.DataLoader(test_data, batch_size=args.batch_size,
                                                  shuffle=False, num_workers=int(args.workers), pin_memory=True)
    model = Model(args).cuda()
    if args.previous_dir != '':
        model_paths = sorted(glob.glob(os.path.join('checkpoint/')))
        for path in model_paths:
            if path.split('/')[-1].startswith('model'):
                model_path = path
                print(model_path)
        pre_dict = torch.load(model_path)
        model_dict = model.state_dict()
        state_dict = {k: v for k, v in pre_dict.items() if k in model_dict.keys()}
        model_dict.update(state_dict)
        model.load_state_dict(model_dict)
    lr = args.lr
    optimizer = optim.Adam(model.parameters(), lr=lr, amsgrad=True)
    best_epoch = 0
    loss_epochs = []
    mpjpes = []
    for epoch in range(1, args.nepoch + 1):
        if args.train:
            loss = train(train_dataloader, model, optimizer, epoch)
            loss_epochs.append(loss * 1000)
        with torch.no_grad():
            p1, p2 = test(actions, test_dataloader, model)
            mpjpes.append(p1)
        if args.train and p1 < args.previous_best:
            best_epoch = epoch
            args.previous_name = save_model(args, epoch, p1, model, 'model')
            args.previous_best = p1
        if args.train:
            logging.info('epoch: %d, lr: %.6f, l: %.4f, p1: %.2f, p2: %.2f, %d: %.2f' % (
            epoch, lr, loss, p1, p2, best_epoch, args.previous_best))
            print('%d, lr: %.6f, l: %.4f, p1: %.2f, p2: %.2f, %d: %.2f' % (
            epoch, lr, loss, p1, p2, best_epoch, args.previous_best))
            if epoch % args.lr_decay_epoch == 0:
                lr *= args.lr_decay_large
                for param_group in optimizer.param_groups:
                    param_group['lr'] *= args.lr_decay_large
            else:
                lr *= args.lr_decay
                for param_group in optimizer.param_groups:
                    param_group['lr'] *= args.lr_decay
        else:
            print('p1: %.2f, p2: %.2f' % (p1, p2))

            break