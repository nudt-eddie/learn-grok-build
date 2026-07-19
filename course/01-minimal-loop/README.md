# Lesson 01: Minimal Training Loop

A step-by-step guide to building a basic neural network training loop in Rust.

## Overview

In this lesson, you will implement a minimal training loop that:
- Initializes a simple neural network
- Runs forward and backward passes
- Updates weights using gradient descent

## Project Structure

```
01-minimal-loop/
├── Cargo.toml          # Project dependencies
├── src/
│   ├── main.rs         # Entry point
│   ├── network.rs      # Neural network definition
│   ├── layer.rs        # Layer implementation
│   ├── tensor.rs       # Tensor operations
│   └── optimizer.rs    # Optimization logic
└── README.md
```

## Dependencies

```toml
[package]
name = "minimal-loop"
version = "0.1.0"
edition = "2021"

[dependencies]
ndarray = "0.15"          # Multi-dimensional arrays
rand = "0.8"              # Random number generation
serde = { version = "1.0", features = ["derive"] }
```

## Key Functions to Implement

### 1. Tensor Operations (`src/tensor.rs`)

```rust
pub struct Tensor {
    pub data: ndarray::Array2<f32>,
    pub grad: Option<ndarray::Array2<f32>>,
}

impl Tensor {
    pub fn new(rows: usize, cols: usize) -> Self;
    pub fn rand(rows: usize, cols: usize) -> Self;
    pub fn zeros(rows: usize, cols: usize) -> Self;
    pub fn add(&self, other: &Tensor) -> Tensor;
    pub fn matmul(&self, other: &Tensor) -> Tensor;
    pub fn sigmoid(&self) -> Tensor;
    pub fn relu(&self) -> Tensor;
    pub fn backward(&mut self, grad: ndarray::Array2<f32>);
}
```

### 2. Layer Definition (`src/layer.rs`)

```rust
pub struct Linear {
    pub weights: Tensor,
    pub bias: Tensor,
}

impl Linear {
    pub fn new(input_size: usize, output_size: usize) -> Self;
    pub fn forward(&self, input: &Tensor) -> Tensor;
    pub fn backward(&mut self, grad: ndarray::Array2<f32>, learning_rate: f32) -> ndarray::Array2<f32>;
}
```

### 3. Neural Network (`src/network.rs`)

```rust
pub struct Network {
    layers: Vec<Linear>,
}

impl Network {
    pub fn new(layer_sizes: &[usize]) -> Self;
    pub fn forward(&self, input: &Tensor) -> Tensor;
    pub fn backward(&mut self, loss_grad: ndarray::Array2<f32>, learning_rate: f32);
    pub fn parameters(&self) -> usize;
}
```

### 4. Optimizer (`src/optimizer.rs`)

```rust
pub struct SGD {
    pub learning_rate: f32,
}

impl SGD {
    pub fn new(learning_rate: f32) -> Self;
    pub fn step(&self, network: &mut Network);
}

pub fn mse_loss(pred: &Tensor, target: &Tensor) -> f32;
pub fn mse_loss_grad(pred: &Tensor, target: &Tensor) -> ndarray::Array2<f32>;
```

### 5. Main Loop (`src/main.rs`)

```rust
fn main() {
    // 1. Create network: input(2) -> hidden(4) -> output(1)
    let mut network = Network::new(&[2, 4, 1]);
    
    // 2. Sample data (XOR problem)
    let inputs = [...];   // Training inputs
    let targets = [...];  // Expected outputs
    
    // 3. Training loop
    for epoch in 0..1000 {
        let mut total_loss = 0.0;
        
        for (x, y) in inputs.iter().zip(targets.iter()) {
            // Forward pass
            let pred = network.forward(x);
            
            // Compute loss
            let loss = mse_loss(&pred, y);
            total_loss += loss;
            
            // Backward pass
            let grad = mse_loss_grad(&pred, y);
            network.backward(grad, 0.1);
        }
        
        if epoch % 100 == 0 {
            println!("Epoch {}: Loss = {:.4}", epoch, total_loss);
        }
    }
}
```

## Implementation Steps

1. **Initialize Cargo project**
   ```bash
   cargo init --name minimal-loop
   ```

2. **Add dependencies to Cargo.toml**

3. **Implement `Tensor` struct** with basic operations (add, matmul, activation functions)

4. **Implement `Linear` layer** with forward and backward methods

5. **Build `Network`** by stacking layers

6. **Add loss functions** (MSE) and gradients

7. **Write training loop** in main.rs

8. **Test with XOR data** - a non-linear problem requiring hidden layers

## Build Instructions

```bash
# Build the project
cargo build --release

# Run the training loop
cargo run --release

# Run with debug output
RUST_LOG=debug cargo run
```

## Expected Output

```
Epoch 0: Loss = 0.2500
Epoch 100: Loss = 0.1250
Epoch 200: Loss = 0.0800
Epoch 500: Loss = 0.0150
Epoch 999: Loss = 0.0012
Training complete!
```

## Key Concepts Covered

- Tensor operations and gradient tracking
- Forward propagation
- Backpropagation
- Gradient descent optimization
- Mini-batch vs stochastic training

## How a Prompt Gets Built: From User Input to ConversationRequest

When a user sends a message, the system assembles a `ConversationRequest` through several stages before sending it to the model. This process is handled by `request_builder.rs` in the `xai-chat-state` crate.

### The Pipeline

1. **User Input Received**: The user submits a message (text, images, or both) which becomes a `ConversationItem::User` entry in the conversation history.

2. **Integrity Check**: Before building the request, `ensure_conversation_integrity()` is called to repair any dangling tool calls or duplicate results.

3. **Context Budget Evaluation**: The system measures total token usage against the context window:
   - If tokens exceed 50% of the context window, pruning is triggered
   - Image payload size is measured precisely (without scanning base64) against a 50 MB ceiling

4. **Mutation Passes** (when needed):
   - **Image Compaction**: If the request body approaches 50 MB, the oldest inline images are replaced with a placeholder text explaining the image was removed
   - **Tool Result Pruning**: Old, large tool results are either hard-cleared (replaced with placeholder) or soft-trimmed (head and tail kept with separator)
   - **Memory Reminder Injection**: A persistent memory reminder is injected into the system message

5. **Request Assembly**: The final `ConversationRequest` is built with:
   - `items`: The conversation history (possibly mutated)
   - `tools`: Tool definitions provided at initialization
   - `model`, `temperature`, `max_output_tokens`, `top_p`: Sampling configuration
   - `x_grok_conv_id`, `x_grok_req_id`: Correlation IDs for tracing

### Key Optimization: Hot Path

If no pruning, memory reminder, or image compaction is needed, the system clones the conversation directly into the request without intermediate mutation passes — avoiding unnecessary allocations and KV-cache prefix rewrites.

### Reference Implementation

See `source/crates/codegen/xai-chat-state/src/actor/request_builder.rs` for the complete implementation including:
- `build_conversation_request()`: Main entry point
- `prune_conversation()`: Old tool result cleanup
- `compact_images_to_byte_budget()`: Image eviction logic
- `inject_memory_reminder()`: System message augmentation

## Next Steps

After completing this lesson, proceed to [Lesson 02: GPU Acceleration](../02-gpu-acceleration/README.md) to add CUDA support.