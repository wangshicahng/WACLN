import math
import torch
import torch.nn as nn
from functools import partial
from timm.models.layers import DropPath

class Mlp(nn.Module):
    def __init__(self, in_features, hidden_features=None, out_features=None, act_layer=nn.GELU, drop=0.):
        super().__init__()
        out_features = out_features or in_features
        hidden_features = hidden_features or in_features
        self.fc1 = nn.Linear(in_features, hidden_features)
        self.act = act_layer()
        self.fc2 = nn.Linear(hidden_features, out_features)
        self.drop = nn.Dropout(drop)

    def forward(self, x):
        x = self.fc1(x)
        x = self.act(x)
        x = self.drop(x)
        x = self.fc2(x)
        x = self.drop(x)
        return x
class Attention(nn.Module):
    def __init__(self, dim, num_heads=8, qkv_bias=False, qk_scale=None, attn_drop=0., proj_drop=0.):
        super().__init__()
        self.num_heads = num_heads
        head_dim = dim // num_heads

        self.scale = qk_scale or head_dim ** -0.5

        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(dim, dim)
        self.proj_drop = nn.Dropout(proj_drop)

    def forward(self, x):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]

        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        attn = self.attn_drop(attn)

        x = (attn @ v).transpose(1, 2).reshape(B, N, C)
        x = self.proj(x)
        x = self.proj_drop(x)
        return x

class Cross_Attention(nn.Module):
    def __init__(self, dim, num_heads=8, qkv_bias=False, qk_scale=None, attn_drop=0., proj_drop=0.):
        super().__init__()
        self.num_heads = num_heads
        head_dim = dim // num_heads
        self.scale = qk_scale or head_dim ** -0.5

        self.linear_q = nn.Linear(dim, dim, bias=qkv_bias)
        self.linear_k = nn.Linear(dim, dim, bias=qkv_bias)
        self.linear_v = nn.Linear(dim, dim, bias=qkv_bias)

        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(dim, dim)
        self.proj_drop = nn.Dropout(proj_drop)

    def forward(self, x_1, x_2, x_3):
        B, N, C = x_1.shape
        q = self.linear_q(x_1).reshape(B, N, self.num_heads, C // self.num_heads).permute(0, 2, 1, 3)
        k = self.linear_k(x_2).reshape(B, N, self.num_heads, C // self.num_heads).permute(0, 2, 1, 3)
        v = self.linear_v(x_3).reshape(B, N, self.num_heads, C // self.num_heads).permute(0, 2, 1, 3)
        
        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        attn = self.attn_drop(attn)

        x = (attn @ v).transpose(1, 2).reshape(B, N, C)
        x = self.proj(x)
        x = self.proj_drop(x)
        return x

class SHR_Block(nn.Module):
    def __init__(self, dim, num_heads, mlp_hidden_dim, qkv_bias=False, qk_scale=None, drop=0., attn_drop=0.,
                 drop_path=0., act_layer=nn.GELU, norm_layer=nn.LayerNorm):
        super().__init__()
        self.norm1_1 = norm_layer(dim)
        self.norm1_2 = norm_layer(dim)
        self.norm1_3 = norm_layer(dim)

        self.attn_1 = Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias, \
            qk_scale=qk_scale, attn_drop=attn_drop, proj_drop=drop)
        self.attn_2 = Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias, \
            qk_scale=qk_scale, attn_drop=attn_drop, proj_drop=drop)
        self.attn_3 = Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias, \
            qk_scale=qk_scale, attn_drop=attn_drop, proj_drop=drop)

        self.drop_path = DropPath(drop_path) if drop_path > 0. else nn.Identity()

        self.norm2 = norm_layer(dim * 3)
        self.mlp = Mlp(in_features=dim * 3, hidden_features=mlp_hidden_dim, act_layer=act_layer, drop=drop)

    def forward(self, x_1, x_2, x_3):
        x_1 = x_1 + self.drop_path(self.attn_1(self.norm1_1(x_1)))
        x_2 = x_2 + self.drop_path(self.attn_2(self.norm1_2(x_2)))
        x_3 = x_3 + self.drop_path(self.attn_3(self.norm1_3(x_3)))
        x = torch.cat([x_1, x_2, x_3], dim=2)
        x = x + self.drop_path(self.mlp(self.norm2(x)))
        x_1 = x[:, :, :x.shape[2] // 3]
        x_2 = x[:, :, x.shape[2] // 3: x.shape[2] // 3 * 2]
        x_3 = x[:, :, x.shape[2] // 3 * 2: x.shape[2]]
        return  x_1, x_2, x_3


class CHI_Block(nn.Module):
    def __init__(self, dim, num_heads, mlp_hidden_dim, qkv_bias=False, qk_scale=None, drop=0., attn_drop=0.,
                 drop_path=0., act_layer=nn.GELU, norm_layer=nn.LayerNorm):
        super().__init__()
        self.norm3_11 = norm_layer(dim)
        self.norm3_12 = norm_layer(dim)
        self.norm3_13 = norm_layer(dim)

        self.norm3_21 = norm_layer(dim)
        self.norm3_22 = norm_layer(dim)
        self.norm3_23 = norm_layer(dim)

        self.norm3_31 = norm_layer(dim)
        self.norm3_32 = norm_layer(dim)
        self.norm3_33 = norm_layer(dim)

        self.attn_1 = Cross_Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias, \
            qk_scale=qk_scale, attn_drop=attn_drop, proj_drop=drop)
        self.attn_2 = Cross_Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias, \
            qk_scale=qk_scale, attn_drop=attn_drop, proj_drop=drop)
        self.attn_3 = Cross_Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias, \
            qk_scale=qk_scale, attn_drop=attn_drop, proj_drop=drop)

        self.drop_path = DropPath(drop_path) if drop_path > 0. else nn.Identity()

        self.norm2 = norm_layer(dim * 3)
        self.mlp = Mlp(in_features=dim * 3, hidden_features=mlp_hidden_dim, act_layer=act_layer, drop=drop)

    def forward(self, x_1, x_2, x_3):
        x_1 = x_1 + self.drop_path(self.attn_1(self.norm3_11(x_2), self.norm3_12(x_3), self.norm3_13(x_1)))    
        x_2 = x_2 + self.drop_path(self.attn_2(self.norm3_21(x_1), self.norm3_22(x_3), self.norm3_23(x_2)))  
        x_3 = x_3 + self.drop_path(self.attn_3(self.norm3_31(x_1), self.norm3_32(x_2), self.norm3_33(x_3)))  

        x = torch.cat([x_1, x_2, x_3], dim=2)
        x = x + self.drop_path(self.mlp(self.norm2(x)))

        x_1 = x[:, :, :x.shape[2] // 3]
        x_2 = x[:, :, x.shape[2] // 3: x.shape[2] // 3 * 2]
        x_3 = x[:, :, x.shape[2] // 3 * 2: x.shape[2]]

        return  x_1, x_2, x_3
def gather_points_by_index(feats, indices):
    B = feats.size(0)
    device = feats.device
    expanded_shape = [B] + [1] * (indices.dim() - 1)
    batch_ids = torch.arange(B, device=device).view(*expanded_shape).expand_as(indices)
    selected = feats[batch_ids, indices]
    return selected


def WAC_clustering(features, num_clusters, k_neighbors, anchor_idx, mask=None):
    with torch.no_grad():
        B, N, D = features.shape
        norm_factor = D ** 0.5
        pairwise_dist = torch.cdist(features, features) / norm_factor
        if mask is not None:
            mask = mask > 0
            max_dist = pairwise_dist.max() + 1
            pairwise_dist = pairwise_dist * mask[:, None, :] + (~mask[:, None, :]) * max_dist

        knn_dists, knn_indices = torch.topk(pairwise_dist, k=k_neighbors, dim=-1, largest=False)
        local_density = torch.exp(-(knn_dists ** 2).mean(dim=-1))
        local_density += torch.rand_like(local_density) * 1e-6
        if mask is not None:
            local_density = local_density * mask
        density_cmp = local_density[:, None, :] > local_density[:, :, None]
        cmp_mask = density_cmp.to(features.dtype)
        max_val = pairwise_dist.view(B, -1).max(dim=-1)[0].view(B, 1, 1)
        min_dist_to_higher_density, _ = (pairwise_dist * cmp_mask + max_val * (1 - cmp_mask)).min(dim=-1)
        alpha = 1.2
        scores = (min_dist_to_higher_density ** alpha) * local_density + (min_dist_to_higher_density + 0.8 * local_density)
        scores[:, anchor_idx] = float('-inf')
        selected_indices = torch.topk(scores, k=num_clusters, dim=-1).indices
        selected_distances = gather_points_by_index(pairwise_dist, selected_indices)
        cluster_assignments = selected_distances.argmin(dim=1)
        batch_idx = torch.arange(B, device=features.device)[:, None].expand(B, num_clusters)
        cluster_ids = torch.arange(num_clusters, device=features.device)[None, :].expand(B, num_clusters)
        cluster_assignments[batch_idx.reshape(-1), selected_indices.reshape(-1)] = cluster_ids.reshape(-1)

        return selected_indices, cluster_assignments


class Transformer(nn.Module):
    def __init__(self, depth=3, embed_dim=512, mlp_hidden_dim=1024, token_num=117, layer_index=1, h=8, drop_rate=0.1, length=27):
        super().__init__()
        drop_path_rate = 0.20
        attn_drop_rate = 0.
        qkv_bias = True
        qk_scale = None
        self.center = (length - 1) // 2
        self.token_num = token_num
        self.layer_index = layer_index
        print(self.token_num, self.layer_index)
        norm_layer = partial(nn.LayerNorm, eps=1e-6)
        self.pos_embed_1 = nn.Parameter(torch.zeros(1, length, embed_dim))
        self.pos_embed_2 = nn.Parameter(torch.zeros(1, length, embed_dim))
        self.pos_embed_3 = nn.Parameter(torch.zeros(1, length, embed_dim))
        self.pos_drop_1 = nn.Dropout(p=drop_rate)
        self.pos_drop_2 = nn.Dropout(p=drop_rate)
        self.pos_drop_3 = nn.Dropout(p=drop_rate)
        dpr = [x.item() for x in torch.linspace(0, drop_path_rate, depth)]
        self.SHR_blocks = nn.ModuleList([
            SHR_Block(
                dim=embed_dim, num_heads=h, mlp_hidden_dim=mlp_hidden_dim, qkv_bias=qkv_bias, qk_scale=qk_scale,
                drop=drop_rate, attn_drop=attn_drop_rate, drop_path=dpr[i], norm_layer=norm_layer)
            for i in range(depth-1)])
        self.CHI_blocks = nn.ModuleList([
            CHI_Block(
                dim=embed_dim, num_heads=h, mlp_hidden_dim=mlp_hidden_dim, qkv_bias=qkv_bias, qk_scale=qk_scale,
                drop=drop_rate, attn_drop=attn_drop_rate, drop_path=dpr[depth-1], norm_layer=norm_layer)
            for i in range(1)])

        self.norm = norm_layer(embed_dim * 3)
    def forward(self, x_1, x_2, x_3, index=None):
        b, f, c = x_1.shape
        x_1 += self.pos_embed_1
        x_2 += self.pos_embed_2
        x_3 += self.pos_embed_3
        x_1 = self.pos_drop_1(x_1)
        x_2 = self.pos_drop_2(x_2)
        x_3 = self.pos_drop_3(x_3)
        for i, blk in enumerate(self.SHR_blocks):
            if i == self.layer_index:
                if index == None:
                    x = torch.cat([x_1, x_2, x_3], dim=2)
                    index, idx_cluster = WAC_clustering(x, self.token_num - 1, 2, self.center)
                    index_center = self.center * torch.ones(b, 1, device=x_knn.device, dtype = index.dtype)
                    index = torch.cat([index, index_center], dim = -1)
                    index, _ = torch.sort(index)
                batch_ind = torch.arange(b, device=x_1.device).unsqueeze(-1)
                x_1 = x_1[batch_ind, index]
                x_2 = x_2[batch_ind, index]
                x_3 = x_3[batch_ind, index]
            x_1, x_2, x_3 = self.SHR_blocks[i](x_1, x_2, x_3)
        x_1, x_2, x_3 = self.CHI_blocks[0](x_1, x_2, x_3)
        x = torch.cat([x_1, x_2, x_3], dim=2)
        x = self.norm(x)

        return x, index