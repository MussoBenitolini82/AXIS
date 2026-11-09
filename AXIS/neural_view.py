"""Inspectable trained XOR neural network: weights, activations, and per-input signals."""
from functools import lru_cache

def _sigmoid(x):
    import math
    return 1.0/(1.0+math.exp(-max(-60,min(60,x))))

@lru_cache(maxsize=1)
def _trained():
    try:
        import torch
    except ImportError:
        return None
    torch.manual_seed(27)
    torch.set_num_threads(1)
    model=torch.nn.Sequential(torch.nn.Linear(2,8),torch.nn.Tanh(),torch.nn.Linear(8,1),torch.nn.Sigmoid())
    x=torch.tensor([[0.,0.],[0.,1.],[1.,0.],[1.,1.]])
    y=torch.tensor([[0.],[1.],[1.],[0.]])
    opt=torch.optim.Adam(model.parameters(),lr=.06)
    for _ in range(650):
        opt.zero_grad();loss=torch.nn.functional.binary_cross_entropy(model(x),y);loss.backward();opt.step()
    model.eval()
    return model

def model_graph(inputs=None):
    model=_trained()
    if model is None:
        return {'available':False,'reason':'PyTorch kurulu değil: py -m pip install torch','nodes':[],'edges':[]}
    import torch
    if inputs is None:inputs=[1.,0.]
    if len(inputs)!=2 or any(float(v) not in (0.,1.) for v in inputs):
        raise ValueError('XOR girdileri yalnızca 0 veya 1 olabilir')
    with torch.no_grad():
        inp=torch.tensor([float(v) for v in inputs]);hidden=model[1](model[0](inp));out=model[3](model[2](hidden))
    activations=[inp.tolist(),hidden.tolist(),out.tolist()]
    nodes=[];edges=[]
    for layer,vals in enumerate(activations):
        for j,value in enumerate(vals):
            nodes.append({'id':f'neuron:{layer}:{j}','label':f'L{layer} N{j}','kind':'neuron','description':f'Katman {layer}, nöron {j}; aktivasyon {value:.5f}','layer':layer,'index':j,'activation':round(value,6)})
    for layer,lin in enumerate((model[0],model[2])):
        weights=lin.weight.detach().tolist()
        for j,row in enumerate(weights):
            for i,w in enumerate(row):
                edges.append({'source':f'neuron:{layer}:{i}','target':f'neuron:{layer+1}:{j}','relation':'weight','weight':round(w,6),'signal':round(w*activations[layer][i],6)})
    with torch.no_grad():
        examples=[{'input':[int(a),int(b)],'prediction':round(float(model(torch.tensor([float(a),float(b)]))),5),'expected':a^b} for a,b in ((0,0),(0,1),(1,0),(1,1))]
    return {'available':True,'trained':True,'architecture':[2,8,1],'description':'Gerçek PyTorch ile XOR üzerinde eğitilmiş küçük ağ. Nöron aktivasyonları seçilen girişe göre değişir; VECTOR LLM modeli değildir.','nodes':nodes,'edges':edges,'parameter_count':sum(p.numel() for p in model.parameters()),'inputs':inputs,'prediction':round(float(out.item()),6),'examples':examples}