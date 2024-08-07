import yaml, os, pathlib, shutil
import numpy as np
from yaml import Loader
from datetime import timedelta
import warnings, subprocess

class project_base():

    def __init__(self):
        self.COPY_FILES=[]
        self.PROJECT_SCRIPT=''
        self.CONTAINER_CMD=None

    def get_top_dir(self,path):
        p=pathlib.Path(path)
        return p.parents[len(p.parents)-2]

    def parse_project_config(self,cfg):
        '''
        Function to be implemented.
        cfg is a configuration dictionary.
        Parse configuration as necessary.
        '''
        pass

    def gen_project_script(self,cfg):
        '''
        Function to be implemented.
        cfg is a configuration dictionary.
        Fill the contents of a project script in self.PROJECT_SCRIPT attribute.
        Fill the list of files to be copied to self.COPY_FILES.
        Those files will be available under the job directory with the same name.
        '''
        pass

    def load_yaml(self,data):
        print('Parsing project configuration at:',data)
        cfg = dict()

        for key,val in yaml.safe_load(open(data,'r').read()).items():
            cfg[key.upper()]=val

        fname = cfg.get('SLURM_CONFIG',None)
        if fname is None:
            raise KeyError('SLURM_CONFIG is required (not found)')

        # check if it exists
        # 0. if starts with '/', abs path search
        # else:
        #   1. current dir
        #   2. the config yaml dir
        if fname.startswith('/') and not os.path.isfile(fname):
            raise FileNotFoundError(f'SLURM_CONFIG not found at {fname}')
        else:
            case0 = os.path.join(os.getcwd(),fname)
            case1 = os.path.join(os.path.dirname(data),fname)

            if os.path.isfile(case0):
                fname = case0
            elif os.path.isfile(case1):
                fname = case1
            else:
                raise FileNotFoundError(f'SLURM_CONFIG not found {fname}')

        print('Parsing slurm   configuration at:',fname)
        slurm_cfg = yaml.safe_load(open(fname,'r').read())
        main_keys = [key.upper() for key in cfg.keys()]
        for key,val in slurm_cfg.items():
            slurm_key = f'SLURM_{key.upper()}'
            if slurm_key in main_keys:
                continue
            cfg[slurm_key] = val

        return cfg


    def parse(self,data):
        # Find slurm yaml first
        cfg = self.load_yaml(data)

        # The "res" will be returned
        res = dict(cfg)

        # Check the storage directory and create this job's output directory
        if not 'STORAGE_DIR' in cfg:
            raise KeyError('STORAGE_DIR key is missing in the configuration file.')
        if not 'SLURM_ARRAY' in cfg:
            raise KeyError('SLURM_ARRAY key is missing in the configuration file.')

        if not os.path.isdir(os.path.expandvars(cfg['STORAGE_DIR'])):
            os.makedirs(cfg['STORAGE_DIR'])
            warnings.warn(f'Storage path {cfg["STORAGE_DIR"]} does not exist. Making one.')
            #raise FileNotFoundError(f'Storage path {cfg["STORAGE_DIR"]} is invalid.')

        sdir=os.path.abspath(os.path.join(os.path.expandvars(cfg['STORAGE_DIR']),f'production_{os.getpid()}'))
        if os.path.isdir(sdir):
            raise OSError(f'Storage directory already have a sub-dir {sdir}')
        res['STORAGE_DIR']=sdir

        # define a job source directory
        res['JOB_SOURCE_DIR'] = os.path.join(sdir,'job_source')

        # add job work directory and output name
        res['JOB_OUTPUT_ID' ] = "$(printf 'output_%d_%04d' $SLURM_ARRAY_JOB_ID $SLURM_ARRAY_TASK_ID)"
        res['JOB_LOG_DIR'   ] = os.path.join(res['STORAGE_DIR'],'slurm_logs')

        if 'SINGULARITY_IMAGE' in cfg:

            if not os.path.isfile(os.path.expandvars(cfg['SINGULARITY_IMAGE'])):
                raise FileNotFoundError(f'Singularity image invalid in the config:{cfg["SINGULARITY_IMAGE"]}')
            # resolve symbolic link
            res['SINGULARITY_IMAGE']=os.path.abspath(os.path.realpath(os.path.expandvars(cfg['SINGULARITY_IMAGE'])))

            # define a copied image name
            if cfg.get('STORE_IMAGE',True):
                res['JOB_IMAGE_NAME']=os.path.join(sdir,f'image_{os.getpid()}.sif')
                res['STORE_IMAGE']=True
            else:
                res['JOB_IMAGE_NAME']=res['SINGULARITY_IMAGE']

            # define paths to be bound to the singularity session
            blist=[]
            blist.append(self.get_top_dir(res['STORAGE_DIR']))
            blist.append(self.get_top_dir(res['JOB_WORK_DIR']))
            blist.append(self.get_top_dir(res['JOB_IMAGE_NAME']))
            blist.append(self.get_top_dir(res['JOB_SOURCE_DIR']))

            # singularity bind flag
            bflag = None
            for pt in np.unique(blist):
                if bflag is None:
                    bflag=f'-B {str(pt)}'
                else:
                    bflag += f',{str(pt)}'

            self.CONTAINER_CMD=f"singularity exec --nv {bflag} {cfg['JOB_IMAGE_NAME']} ./run.sh"

        elif 'SHIFTER_IMAGE' in cfg:
            #try:
            #    subprocess.check_output(["shifterimg", "lookup", cfg['SHIFTER_IMAGE']])
            #except subprocess.CalledProcessError:
            #    raise FileNotFoundError(f'Shifter image not found: {cfg["SHIFTER_IMAGE"]}')
                
            if cfg.get('STORE_IMAGE',False):
                raise NotImplementedError('STORE_IMAGE option is not available when using shifter')
            res['STORE_IMAGE']=False
            res['JOB_IMAGE_NAME']=cfg['SHIFTER_IMAGE']
            self.CONTAINER_CMD=f"shifter --image={res['JOB_IMAGE_NAME']}"
            if 'SLURM_GPUS' in res or 'SLURM_GPUS-PER-TASK' in res:
                self.CONTAINER_CMD += " --module=gpu "
            self.CONTAINER_CMD += " ./run.sh"

        # ensure singularity image is valid
        else:
            raise KeyError('SINGULARITY_IMAGE or SHIFTER_IMAGE must be specified in the config.')



        return res

    def gen_slurm_flags(self,cfg):

        # Find slurm related parameters
        params = {key.lower().replace('slurm_',''):cfg[key] for key in cfg.keys() if key.lower().startswith('slurm_')}
        params.pop('config')

	# Parse params that need parsing
        # SLURM_TIME converted to seconds automatically
        # convert back to HH:MM:SS format
        #if 'time' in params.keys():
	#    print(type(params['time']))
        #    print(params['time'])
        #    params['time'] = str(timedelta(seconds=params['time']))   

        # Set required params in case not set by config                                                                                                                                      
        defaults = dict(nodes=1,
            ntasks=1,
            output=f"{cfg['JOB_LOG_DIR']}/slurm-%A-%a.out",
            error=f"{cfg['JOB_LOG_DIR']}/slurm-%A-%a.out",
            )
        for key in defaults.keys():
            if not key in params.keys():
                params[key]=defaults[key]

        # Complete the flags
        flags = f'#SBATCH --job-name=dntp-{os.getpid()}\n'
        for key,val in params.items():
            flags += f'#SBATCH --{key}={val}\n'
        return flags


    def gen_submission_script(self,cfg):

        script=f'#!/bin/bash\n{self.gen_slurm_flags(cfg)}'

        script += f'''
mkdir -p {cfg['JOB_WORK_DIR']} 
cd {cfg['JOB_WORK_DIR']}
echo {cfg['JOB_WORK_DIR']}

LOCAL_WORK_DIR=$(printf "job_%d_%04d" $SLURM_ARRAY_JOB_ID $SLURM_ARRAY_TASK_ID)

scp -r {cfg['JOB_SOURCE_DIR']} $LOCAL_WORK_DIR

cd $LOCAL_WORK_DIR

export PATH=$HOME/.local/bin:$PATH
export CUDA_HOME=/usr/local/cuda

printenv &> jobinfo_env.txt
uname -a &> jobinfo_node.txt

chmod 774 run.sh

{self.CONTAINER_CMD}

date
echo "Copying the output"

cd ..
scp -r $LOCAL_WORK_DIR {cfg['STORAGE_DIR']}/
    
    '''
        return script


    def generate(self,cfg):

        # parse the configuration            
        cfg = self.parse(cfg)
        cfg_data = yaml.dump(cfg,default_flow_style=False)

        jsdir = cfg['JOB_SOURCE_DIR']
        sdir  = cfg['STORAGE_DIR']
        ldir  = cfg['JOB_LOG_DIR']

        try:
            # Report the job top directory and clean-up method
            print(f'Constructing a new production with ID {os.getpid()}')
            print('\nTo clean up this production, simply execute the master directory:')
            print(f'\n    rm -r {sdir}\n')
            # Create the job source and the storage directories
            print(f'Creating a dir: {sdir}')
            os.makedirs(sdir)
            print(f'Creating a dir: {jsdir}')
            os.makedirs(jsdir)
            print(f'Creating a dir: {ldir}')
            os.makedirs(ldir)
            print(f'Using a container image: {cfg["JOB_IMAGE_NAME"]}')
            if cfg['STORE_IMAGE']:
                print('Copying the singularity image file.')
                print(f'Destination: {cfg["JOB_IMAGE_NAME"]}')
                shutil.copyfile(cfg['SINGULARITY_IMAGE'],cfg['JOB_IMAGE_NAME'])

            # Generate a submission script
            with open(os.path.join(jsdir,'submit.sh'),'w') as f:
                f.write(self.gen_submission_script(cfg))
                f.close()

            #
            # Perform project-specific tasks
            #
            # Parse configuration for the project
            self.parse_project_config(cfg)
            # Generate a project script contents
            self.gen_project_script(cfg)
            # Generate a job script
            with open(os.path.join(jsdir,'run.sh'),'w') as f:
                f.write(self.PROJECT_SCRIPT)
                f.close()
            # Copy necessary files
            for f in self.COPY_FILES:
                if os.path.isdir(f):
                    src,target=f,os.path.basename(f)
                    shutil.copytree(src,os.path.join(jsdir,target))
                elif os.path.isfile(f):
                    src,target=f,os.path.basename(f)
                    shutil.copyfile(src,os.path.join(jsdir,target))
                else:
                    raise ValueError("can only copy files or directories")

            #
            # Log the config contents
            #
            with open(os.path.join(jsdir,'source.yaml'),'w') as f:
                f.write(cfg_data)
                f.close()


        except (KeyError, ValueError, OSError, IsADirectoryError) as e:
            if os.path.isdir(jsdir):
                shutil.rmtree(jsdir)
            if cfg['STORE_IMAGE'] and os.path.isfile(cfg['JOB_IMAGE_NAME']):
                os.remove(cfg['JOB_IMAGE_NAME'])
            if os.path.isdir(sdir):
                shutil.rmtree(sdir)
            if os.path.isdir(ldir):
                os.rmdir(ldir)
            print('Encountered an error. Aborting...')
            raise e

        print(f'Created job source scripts at {jsdir}')
        print(f'Job output will be sent to {sdir}')
        print(f'\nTo submit a job, type:\n\nsbatch {os.path.join(jsdir,"submit.sh")}\n')
        return True


class project_example(project_base):


    def parse_project_config(self,cfg):

        return

    def gen_project_script(self,cfg):

        return '#!/bin/bash\necho "hello world"\n'

if __name__ == '__main__':
    import sys
    if not len(sys.argv) == 2:
        print(f'Invalid number of the arguments ({len(sys.argv)})')
        print(f'Usage: {os.path.basename(__file__)} $JOB_CONFIGURATION_YAML')
        sys.exit(1)

    if not sys.argv[1].endswith('.yaml'):
        print('The argument must be a yaml file with .yaml extension.')
        print(f'(provided: {os.path.basename(sys.argv[1])})')
        sys.exit(2)

    p=project_example()
    p.generate(sys.argv[1])
    sys.exit(0)
