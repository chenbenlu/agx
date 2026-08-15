from __future__ import annotations

import argparse
from pathlib import Path
import sys

import torch
import torch.nn.functional as F

from .modeling import default_grounding_dino_repo_path, import_grounding_dino_modules


class GroundingDINOIsaacWrapper(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(
        self,
        inputs,
        input_ids,
        attention_mask,
        position_ids,
        token_type_ids,
        text_token_mask,
    ):
        from groundingdino.util.misc import inverse_sigmoid, nested_tensor_from_tensor_list

        tokenized_for_encoder = {
            "input_ids": input_ids,
            "attention_mask": text_token_mask.bool(),
            "token_type_ids": token_type_ids,
            "position_ids": position_ids,
        }

        bert_output = self.model.bert(**tokenized_for_encoder)
        encoded_text = self.model.feat_map(bert_output["last_hidden_state"])
        text_dict = {
            "encoded_text": encoded_text,
            "text_token_mask": attention_mask.bool(),
            "position_ids": position_ids,
            "text_self_attention_masks": text_token_mask.bool(),
        }

        samples = nested_tensor_from_tensor_list(list(inputs))
        self.model.set_image_tensor(samples)

        srcs = []
        masks = []
        for level, feat in enumerate(self.model.features):
            src, mask = feat.decompose()
            srcs.append(self.model.input_proj[level](src))
            masks.append(mask)

        if self.model.num_feature_levels > len(srcs):
            current_len = len(srcs)
            for level in range(current_len, self.model.num_feature_levels):
                if level == current_len:
                    src = self.model.input_proj[level](self.model.features[-1].tensors)
                else:
                    src = self.model.input_proj[level](srcs[-1])
                mask = F.interpolate(
                    samples.mask[None].float(), size=src.shape[-2:]
                ).to(torch.bool)[0]
                pos_level = self.model.backbone[1](type(samples)(src, mask)).to(src.dtype)
                srcs.append(src)
                masks.append(mask)
                self.model.poss.append(pos_level)

        hs, reference, _, _, _ = self.model.transformer(
            srcs,
            masks,
            None,
            self.model.poss,
            None,
            None,
            text_dict,
        )

        outputs_coord_list = []
        for layer_ref_sig, layer_bbox_embed, layer_hs in zip(
            reference[:-1],
            self.model.bbox_embed,
            hs,
        ):
            layer_delta_unsig = layer_bbox_embed(layer_hs)
            layer_outputs_unsig = layer_delta_unsig + inverse_sigmoid(layer_ref_sig)
            outputs_coord_list.append(layer_outputs_unsig.sigmoid())
        outputs_coord_list = torch.stack(outputs_coord_list)

        outputs_class = torch.stack(
            [
                layer_cls_embed(layer_hs, text_dict)
                for layer_cls_embed, layer_hs in zip(self.model.class_embed, hs)
            ]
        )

        self.model.unset_image_tensor()
        return outputs_class[-1], outputs_coord_list[-1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the open-source GroundingDINO model to an Isaac ROS style ONNX graph."
    )
    parser.add_argument(
        "--repo-path",
        default=str(default_grounding_dino_repo_path()),
        help="Path to the GroundingDINO repository checkout.",
    )
    parser.add_argument(
        "--config-path",
        default="",
        help="GroundingDINO config path. Defaults to GroundingDINO_SwinT_OGC.py under --repo-path.",
    )
    parser.add_argument(
        "--weights-path",
        required=True,
        help="Path to groundingdino_swint_ogc.pth.",
    )
    parser.add_argument(
        "--output-path",
        required=True,
        help="Output ONNX file path.",
    )
    parser.add_argument("--height", type=int, default=544, help="Export input height.")
    parser.add_argument("--width", type=int, default=960, help="Export input width.")
    parser.add_argument(
        "--device",
        default="cpu",
        help="Export device. Use cpu unless your export environment already has working CUDA + ops.",
    )
    parser.add_argument("--opset", type=int, default=17, help="ONNX opset version.")
    return parser.parse_args()


def load_model(repo_path: Path, config_path: Path, weights_path: Path, device: str):
    modules = import_grounding_dino_modules(repo_path)
    args = modules["SLConfig"].fromfile(str(config_path))
    args.device = device
    model = modules["build_model"](args)
    checkpoint = torch.load(str(weights_path), map_location="cpu")
    model.load_state_dict(modules["clean_state_dict"](checkpoint["model"]), strict=False)
    model.eval()
    model.to(torch.device(device))
    return model


def main() -> None:
    args = parse_args()
    try:
        import onnx  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "The `onnx` Python package is required for export. "
            "Install it inside your AGX Orin/Isaac ROS environment first."
        ) from exc

    repo_path = Path(args.repo_path).expanduser().resolve()
    config_path = (
        Path(args.config_path).expanduser().resolve()
        if args.config_path
        else repo_path / "groundingdino/config/GroundingDINO_SwinT_OGC.py"
    )
    weights_path = Path(args.weights_path).expanduser().resolve()
    output_path = Path(args.output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model = load_model(repo_path, config_path, weights_path, args.device)
    wrapper = GroundingDINOIsaacWrapper(model).eval()

    inputs = torch.randn(1, 3, args.height, args.width, device=args.device, dtype=torch.float32)
    input_ids = torch.zeros((1, 256), device=args.device, dtype=torch.int64)
    attention_mask = torch.ones((1, 256), device=args.device, dtype=torch.uint8)
    position_ids = torch.arange(256, device=args.device, dtype=torch.int64).unsqueeze(0)
    token_type_ids = torch.zeros((1, 256), device=args.device, dtype=torch.int64)
    text_token_mask = torch.eye(256, device=args.device, dtype=torch.uint8).unsqueeze(0)

    torch.onnx.export(
        wrapper,
        (
            inputs,
            input_ids,
            attention_mask,
            position_ids,
            token_type_ids,
            text_token_mask,
        ),
        str(output_path),
        input_names=[
            "inputs",
            "input_ids",
            "attention_mask",
            "position_ids",
            "token_type_ids",
            "text_token_mask",
        ],
        output_names=["pred_logits", "pred_boxes"],
        opset_version=args.opset,
        do_constant_folding=True,
    )

    print(f"Exported ONNX to: {output_path}")


if __name__ == "__main__":
    main()
